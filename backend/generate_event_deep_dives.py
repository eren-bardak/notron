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
from deep_dive.models import EventAnalysis, ResearchBundle
from event_images import refresh_event_covers
from numeric_data_quality import valid_analysis_timeline
from pipeline_visibility import enforce_previous_year_gate, publish_ready_events, valid_questions, valid_numeric_data
from popularity import POLICY, current_score
from editorial_quality import RESEARCH_REVISION, current_editorial


load_dotenv()

EVENT_WINDOW_HOURS = POLICY["event_window_hours"]
MAX_EVENTS_PER_RUN = int(os.getenv("MAX_DEEP_DIVES_PER_RUN", "20"))


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
        .select("id,created_at,numeric_data,enough_data,is_visible,problem_supported,source_count,popularity_score,popularity_updated_at")
        .gte("created_at", cutoff.isoformat())
        .lte("created_at", datetime.now(timezone.utc).isoformat())
        .order("popularity_score", desc=True)
        .execute()
        .data
    )

    eligible = [event for event in events if (event.get("source_count") or 0) >= 2
                and current_score(event, datetime.now(timezone.utc)) >= POLICY["display_threshold"]]
    ids = [int(event["id"]) for event in eligible]
    all_ids = [int(event["id"]) for event in events]
    stored = (db.table("event_analyses").select("event_id,status,analysis,research").in_("event_id", all_ids).execute().data) if all_ids else []
    # Previously ready events must disappear even if their replacement research fails.
    rejected = enforce_previous_year_gate(db, events, stored)
    print(f"Revalidated previous_year={datetime.now(timezone.utc).year - 1} | rejected={len(rejected)}", flush=True)
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    stored_by_id = {int(row["event_id"]): row for row in stored}
    # Reuse only analyses reviewed under the current editorial policy. Old ballot rows remain stored.
    ready = {int(row["event_id"]) for row in stored if row.get("status") == "ready" and current_editorial(row.get("analysis")) and (row["analysis"].get("editorial_review") or {}).get("tradeoff_present") is True and (row["analysis"].get("editorial_review") or {}).get("balanced_choices") is True and valid_questions(row.get("analysis")) and row["analysis"].get("schema_version") == 2 and row["analysis"].get("question_revision") in (2, 3)}
    pending = eligible if args.force else [event for event in eligible if not event.get("enough_data") or not valid_numeric_data(event.get("numeric_data")) or int(event["id"]) not in ready]
    for event in eligible:
        old_questions = (stored_by_id.get(int(event["id"]), {}).get("analysis") or {}).get("binary_questions") or []
        if event not in pending and any(not complete_question_text(q.get("question")) for q in old_questions):
            pending.append(event)
    pending.sort(key=lambda event: (int(event["id"]) != args.prioritize_event, not event.get("is_visible", False)))
    failures = 0
    # Update existing covers first; missing-data research may take much longer.
    refresh_cover_questions(db, client, model, [event_id for event_id in ids if event_id in ready], max_reviews=MAX_EVENTS_PER_RUN)

    for event in pending[:MAX_EVENTS_PER_RUN]:
        event_id = int(event["id"])
        print(f"Deep dive research | event={event_id}")

        try:
            cached = stored_by_id.get(event_id, {})
            if not args.force and (cached.get("research") or {}).get("editorial_revision") == RESEARCH_REVISION and valid_numeric_data(event.get("numeric_data")):
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

            if not valid_numeric_data([series.model_dump() for series in research.numeric_series]):
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
                reason = f"no valid sourced event evidence (timelines require observed {datetime.now(timezone.utc).year - 1} data)"
                print(f"Deep dive skipped | event={event_id} | {reason}")
                continue

            old_analysis = cached.get("analysis") or {}
            question_only = False
            if (not args.force and current_editorial(old_analysis) and old_analysis.get("schema_version") == 2
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

        except Exception as error:
            # A temporary API failure must not permanently reject the event.
            print(f"Deep dive failed | event={event_id} | error={error}")
            failures += 1

    # Covers are edited separately so a headline refresh never invalidates ballots.
    refresh_cover_questions(db, client, model, [event_id for event_id in ids if event_id not in ready], max_reviews=MAX_EVENTS_PER_RUN)
    # Photo review also covers already-ready events and does not alter question IDs.
    refresh_event_covers(db, client, model, ids, max_reviews=MAX_EVENTS_PER_RUN)
    published = publish_ready_events(db)
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
