"""Refresh current cards and optional trade-off questions using saved evidence."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from supabase import create_client
from deep_dive.cover_question import refresh_cover_questions
from deep_dive.analyze_event import review_questions, complete_question_text
from deep_dive.models import EventAnalysis, ResearchBundle
from deep_dive.editorial_overrides import event_tradeoff
from pipeline_visibility import ready_event_ids
from popularity import read_all


def refresh_tradeoffs(db, client, model, ids):
    if not ids:
        return
    rows = read_all(db, "event_analyses", "event_id,analysis,research,generated_at", "event_id", ids, order_by="event_id")
    for row in rows:
        original = row.get("analysis") or {}
        review = original.get("editorial_review") or {}
        preferred = event_tradeoff(row.get("research") or {})
        if (review.get("tradeoff_present") is True and review.get("balanced_choices") is True
                and all(complete_question_text(q.get("question")) for q in original.get("binary_questions", []))):
            if not preferred or all(q.get("question") == preferred for q in original.get("binary_questions", [])):
                continue
        feedback = ""
        for attempt in range(2):
            try:
                research = ResearchBundle.model_validate(row["research"])
                draft = {**original, "question_revision": 3, "binary_questions": [q for q in original.get("binary_questions", []) if q.get("question_type") == "metric"]}
                analysis = EventAnalysis.model_validate(draft)
                questions = review_questions(client, model, research, analysis.binary_questions, analysis.charts, analysis=analysis, feedback=feedback)
                at = datetime.now(timezone.utc).isoformat()
                updated = {**original, "question_revision": 3, "binary_questions": [q.model_dump(mode="json") for q in questions],
                           "editorial_review": analysis.editorial_review.model_dump(mode="json"), "generated_at": at}
                write = db.table("event_analyses").update({"analysis": updated, "generated_at": at}).eq("event_id", row["event_id"]).eq("status", "ready")
                if row.get("generated_at"):
                    write = write.eq("generated_at", row["generated_at"])
                if not write.execute().data:
                    raise RuntimeError("Event changed during review; retain its newer version")
                print(f"Trade-off question ready | event={row['event_id']} | {questions[0].question}", flush=True)
                break
            except Exception as error:
                feedback = str(error)
                if attempt == 1:
                    print(f"Trade-off question deferred | event={row['event_id']} | {feedback}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tradeoffs", action="store_true")
    args = parser.parse_args()
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    events = read_all(db, "events", "id,title,created_at,enough_data,numeric_data,source_count,popularity_score,popularity_updated_at")
    analyses = read_all(db, "event_analyses", "event_id,status,analysis")
    ids = ready_event_ids(events, analyses)[:20]
    titles = {row["id"]: row["title"] for row in events}
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_DEEP_DIVE_MODEL", "gpt-5.4-mini")
    if args.tradeoffs:
        refresh_tradeoffs(db, client, model, ids)
    refresh_cover_questions(db, client, model, ids)
    rows = read_all(db, "event_analyses", "event_id,analysis", "event_id", ids, order_by="event_id") if ids else []
    cards = []
    for row in rows:
        analysis = row.get("analysis") or {}
        cards.append({"event_id": row["event_id"], "title": titles[row["event_id"]],
                      "headline": analysis.get("card_headline"),
                      "summary": analysis.get("card_summary"), "bridge": analysis.get("card_question_bridge"),
                      "question": analysis.get("cover_question"), "revision": analysis.get("card_story_revision"),
                      "cover_revision": analysis.get("cover_question_revision"), "cover_tradeoff": analysis.get("cover_tradeoff"),
                      "data_question": analysis.get("binary_questions"), "review": analysis.get("editorial_review"),
                      "sources": analysis.get("cover_question_source_urls")})
    Path("card-stories.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n")
    missing = [card["event_id"] for card in cards if card["revision"] != 2 or not card["headline"] or not card["summary"] or not card["bridge"]
               or card["cover_revision"] != 2 or card["cover_tradeoff"] is not True
               or (args.tradeoffs and not ((card.get("review") or {}).get("tradeoff_present") is True and (card.get("review") or {}).get("balanced_choices") is True
                   and all(complete_question_text(q.get("question")) for q in card.get("data_question") or [])))]
    print(f"Card copy updated: {len(cards) - len(missing)}/{len(ids)}")
    if missing or len(cards) != len(ids):
        raise RuntimeError(f"Some card stories could not be refreshed: {missing}")


if __name__ == "__main__":
    main()
