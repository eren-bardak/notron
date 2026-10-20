import argparse
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError
from supabase import create_client

from deep_dive.analyze_event import analyze_event, review_questions, complete_question_text
from deep_dive.research_event import load_event, research_event
from deep_dive.save_analysis import save_analysis
from deep_dive.cover_question import refresh_cover_questions
from deep_dive.background_context import refresh_background_contexts
from deep_dive.models import EventAnalysis, ResearchBundle
from event_images import refresh_event_covers
from numeric_data_quality import valid_analysis_timeline, has_event_evidence
from pipeline_visibility import enforce_previous_year_gate, publish_ready_events, valid_questions, valid_numeric_data
from popularity import POLICY, current_score, event_thresholds
from editorial_quality import RESEARCH_REVISION, current_editorial, publication_quality
from daily_budget import budget_client, coverage_rank, ledger, BudgetError
from event_catalog import balanced_event
from country_scope import country_eligible


load_dotenv()

EVENT_WINDOW_HOURS = POLICY["event_window_hours"]
ECONOMY_MODE = os.getenv("NOTRON_PIPELINE_MODE") == "economy"
MAX_EVENTS_PER_RUN = max(1, min(3 if ECONOMY_MODE else 20, int(os.getenv("MAX_DEEP_DIVES_PER_RUN", "20"))))


def main() -> None:
    """Research ranked clusters, then publish complete files with one data question."""

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate recent analyses even when numeric data already exists.",
    )
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Apply the sourced event-evidence gate to saved events without research or OpenAI calls.",
    )
    parser.add_argument("--prioritize-event", type=int, help="Refresh this current event first, without changing its publication rank.")
    args = parser.parse_args()

    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    if args.validate_only:
        publish_ready_events(db)
        return
    model = os.getenv("OPENAI_DEEP_DIVE_MODEL", "gpt-5.4-mini")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=EVENT_WINDOW_HOURS)

    events = (
        db.table("events")
        .select("id,created_at,category,title,data,numeric_data,enough_data,is_visible,problem_supported,source_count,left_source_count,right_source_count,article_count,popularity_score,popularity_updated_at")
        .gte("created_at", cutoff.isoformat())
        .lte("created_at", datetime.now(timezone.utc).isoformat())
        .order("popularity_score", desc=True)
        .execute()
        .data
    )

    now = datetime.now(timezone.utc)
    eligible = [event for event in events if country_eligible(event) and balanced_event(event) and (event.get('data') or {}).get('newsworthy') is not False and not (event.get('data') or {}).get('publication_excluded_reason')]
    thresholds = event_thresholds(eligible, now)
    eligible = [event for event in eligible if current_score(event, now) >= thresholds[int(event['id'])]]
    ids = [int(event["id"]) for event in eligible]
    all_ids = [int(event["id"]) for event in events]
    stored = (db.table("event_analyses").select("event_id,status,analysis,research").in_("event_id", all_ids).execute().data) if all_ids else []
    # Previously ready events must disappear even if their replacement research fails.
    rejected = enforce_previous_year_gate(db, events, stored)
    print(f"Revalidated previous_year={datetime.now(timezone.utc).year - 1} | rejected={len(rejected)}", flush=True)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"], max_retries=0 if ECONOMY_MODE else 2, timeout=180)
    client = budget_client(client, db)
    stored_by_id = {int(row["event_id"]): row for row in stored}
    # Reuse only analyses reviewed under the current editorial policy. Old ballot rows remain stored.
    ready = {int(row["event_id"]) for row in stored if row.get("status") == "ready" and current_editorial(row.get("analysis")) and (row["analysis"].get("editorial_review") or {}).get("tradeoff_present") is True and (row["analysis"].get("editorial_review") or {}).get("balanced_choices") is True and valid_questions(row.get("analysis")) and row["analysis"].get("schema_version") == 2 and row["analysis"].get("question_revision") in (2, 3)}
    pending = eligible if args.force else [event for event in eligible if not event.get("enough_data") or not valid_analysis_timeline((stored_by_id.get(int(event["id"])) or {}).get("analysis"), event.get("numeric_data")) or int(event["id"]) not in ready]
    for event in eligible:
        old_questions = (stored_by_id.get(int(event["id"]), {}).get("analysis") or {}).get("binary_questions") or []
        if event not in pending and any(not complete_question_text(q.get("question")) for q in old_questions):
            pending.append(event)
    pending.sort(key=lambda event: (int(event["id"]) != args.prioritize_event, not event.get("is_visible", False)))
    selected_ids = []
    if ECONOMY_MODE:
        ranked = sorted(eligible, key=coverage_rank)
        selected_ids = ledger(db, 'select', p_event_ids=[int(e['id']) for e in ranked[:3]])['event_ids']
        selected_ids = [event_id for event_id in selected_ids if event_id in {int(e['id']) for e in ranked}]
        # Reuse this day's selection after a failed run; never buy a second batch.
        pending = [e for e in ranked if int(e['id']) in selected_ids and e in pending]
    failures = 0
    # Update existing covers first; missing-data research may take much longer.
    if not ECONOMY_MODE:
        refresh_cover_questions(db, client, model, [event_id for event_id in ids if event_id in ready], max_reviews=MAX_EVENTS_PER_RUN)

    for event in pending[:MAX_EVENTS_PER_RUN]:
        event_id = int(event["id"])
        print(f"Deep dive research | event={event_id}")

        try:
            cached = stored_by_id.get(event_id, {})
            if not args.force and (cached.get("research") or {}).get("editorial_revision") == RESEARCH_REVISION and (valid_numeric_data(event.get("numeric_data")) or has_event_evidence(cached.get("research"))):
                try:
                    research = ResearchBundle.model_validate(cached["research"])
                    print(f"Refresh questions from saved research | event={event_id}")
                except ValidationError:
                    research = research_event(client, model, event_id, load_event(db, event_id))
            else:
                payload = load_event(db, event_id)
                research = research_event(client, model, event_id, payload)
            if research.event_id != event_id:
                raise ValueError("Research returned a different event ID; no analysis was saved.")

            # Keep independently valid measurements; unsupported charts never block a sourced story.
            research.numeric_series = [series for series in research.numeric_series
                                       if valid_numeric_data([series.model_dump(mode="json")])]
            if not research.numeric_series:
                research.metric_candidates = []
            if not research.numeric_series and not has_event_evidence(research.model_dump(mode="json")):
                db.table("events").update(
                    {
                        "enough_data": False,
                        "is_visible": False,
                        "numeric_data": [series.model_dump(mode="json") for series in research.numeric_series],
                        "problem_supported": research.problem_supported,
                        "central_problem": research.central_problem,
                    }
                ).eq("id", event_id).execute()
                db.table("event_analyses").upsert(
                    {
                        "event_id": event_id,
                        "status": "insufficient_data",
                        "research": research.model_dump(mode="json"),
                        "analysis": {},
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    on_conflict="event_id",
                ).execute()
                reason = "no numerical evidence or explanation supported by two source domains"
                print(f"Deep dive skipped | event={event_id} | {reason}")
                continue

            old_analysis = cached.get("analysis") or {}
            question_only = False
            if (not args.force and current_editorial(old_analysis) and publication_quality(old_analysis) and old_analysis.get("schema_version") == 2
                    and old_analysis.get("question_revision") == 3 and valid_questions(old_analysis)
                    and valid_analysis_timeline(old_analysis, [series.model_dump(mode="json") for series in research.numeric_series])):
                # A wording repair needs no second data-story generation or web search.
                analysis = EventAnalysis.model_validate(old_analysis)
                question_only = True
                analysis.binary_questions = review_questions(client, model, research, analysis.binary_questions, analysis.charts, analysis=analysis)
                analysis.generated_at = datetime.now(timezone.utc).isoformat()
            else:
                analysis = analyze_event(client, model, research)
            if analysis.event_id != event_id:
                raise ValueError("Analysis returned a different event ID; no analysis was saved.")
            save_analysis(db, research, analysis, preserve_card_fields=question_only)
            print(
                f"Deep dive ready | event={event_id} | "
                f"metrics={len(research.metric_candidates)} | "
                f"points={sum(len(series.points) for series in research.numeric_series)} | "
                f"charts={len(analysis.charts)}"
            )

        except BudgetError:
            raise
        except Exception as error:
            # A temporary API failure must not permanently reject the event.
            print(f"Deep dive failed | event={event_id} | error={error}")
            failures += 1

    # Covers are edited separately so a headline refresh never invalidates ballots.
    if not ECONOMY_MODE:
        refresh_cover_questions(db, client, model, [event_id for event_id in ids if event_id not in ready], max_reviews=MAX_EVENTS_PER_RUN)
        # Photo review also covers already-ready events and does not alter question IDs.
        refresh_event_covers(db, client, model, ids, max_reviews=MAX_EVENTS_PER_RUN)
    published = publish_ready_events(db)
    if ECONOMY_MODE:
        verified = set(selected_ids).intersection(published)
        target = min(3, len(eligible))
        print(f'Daily batch verification | target={target} | published={len(verified)}', flush=True)
        if len(verified) != target:
            raise RuntimeError(f'Daily batch incomplete: {len(verified)}/{target} cross-spectrum stories passed publication checks.')
    background_failures = 0 if ECONOMY_MODE else refresh_background_contexts(db, client, model, published)
    if ECONOMY_MODE:
        print("Economy mode: optional cover/photo/background passes skipped; core editorial checks retained.")
    if background_failures:
        print(f"Background context deferred for {background_failures}; current event data retained.")
    if args.prioritize_event is not None and args.prioritize_event not in published:
        raise RuntimeError(f"Requested event {args.prioritize_event} did not finish with a current, publishable editorial review; inspect its evidence and eligibility.")
    try:
        db.table("event_comments").select("user_id").limit(0).execute()
        print("Family preview readiness | Writer account column ready")
    except Exception as error:
        if getattr(error, "code", None) == "42703":
            print("Family preview readiness | Writer posting requires backend/writer_identity_migration.sql")
        else:
            print("Family preview readiness | Writer schema check unavailable")
    if failures:
        raise RuntimeError(f"{failures} deep dives failed. Successful analyses were retained; retry the pipeline.")


if __name__ == "__main__":
    main()
