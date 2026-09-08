"""Refresh only public card copy; retain questions, votes, charts and backgrounds."""
import json
import os
from pathlib import Path

from openai import OpenAI
from supabase import create_client
from deep_dive.cover_question import refresh_cover_questions
from pipeline_visibility import ready_event_ids
from popularity import read_all


def main():
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    events = read_all(db, "events", "id,title,created_at,enough_data,numeric_data,source_count,popularity_score,popularity_updated_at")
    analyses = read_all(db, "event_analyses", "event_id,status,analysis")
    ids = ready_event_ids(events, analyses)[:20]
    titles = {row["id"]: row["title"] for row in events}
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_DEEP_DIVE_MODEL", "gpt-5.4-mini")
    refresh_cover_questions(db, client, model, ids)
    rows = read_all(db, "event_analyses", "event_id,analysis", "event_id", ids, order_by="event_id") if ids else []
    cards = []
    for row in rows:
        analysis = row.get("analysis") or {}
        cards.append({"event_id": row["event_id"], "title": titles[row["event_id"]],
                      "summary": analysis.get("card_summary"), "bridge": analysis.get("card_question_bridge"),
                      "question": analysis.get("cover_question"), "revision": analysis.get("card_story_revision"),
                      "sources": analysis.get("cover_question_source_urls")})
    Path("card-stories.json").write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n")
    missing = [card["event_id"] for card in cards if card["revision"] != 1 or not card["summary"] or not card["bridge"]]
    print(f"Card copy updated: {len(cards) - len(missing)}/{len(ids)}")
    if missing or len(cards) != len(ids):
        raise RuntimeError(f"Some card stories could not be refreshed: {missing}")


if __name__ == "__main__":
    main()
