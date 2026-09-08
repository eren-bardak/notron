"""Refresh explanatory background only; retain every existing chart and ballot."""
import json
import os
from pathlib import Path

from openai import OpenAI
from supabase import create_client
from deep_dive.background_context import refresh_background_contexts, CONTEXT_REVISION
from pipeline_visibility import ready_event_ids
from popularity import read_all


def main():
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    events = read_all(db, "events", "id,title,created_at,enough_data,numeric_data,source_count,popularity_score,popularity_updated_at")
    rows = read_all(db, "event_analyses", "event_id,status,analysis")
    ids = ready_event_ids(events, rows)[:20]
    before = {row["event_id"]: row["analysis"] for row in rows if row["event_id"] in ids}
    failures = refresh_background_contexts(db, OpenAI(api_key=os.environ["OPENAI_API_KEY"]), os.getenv("OPENAI_DEEP_DIVE_MODEL", "gpt-5.4-mini"), ids)
    updated = read_all(db, "event_analyses", "event_id,analysis", "event_id", ids, order_by="event_id") if ids else []
    report = []
    for row in updated:
        old, new = before[row["event_id"]], row["analysis"]
        untouched = all(old.get(key) == new.get(key) for key in ("binary_questions", "charts", "editorial_review", "card_headline", "card_summary", "cover_question"))
        report.append({"event_id": row["event_id"], "background": new.get("background"),
                       "context": new.get("background_context"), "questions_and_charts_preserved": untouched})
    Path("background-contexts.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    ready = [row for row in report if row["questions_and_charts_preserved"] and (row.get("context") or {}).get("revision") == CONTEXT_REVISION]
    print(f"Backgrounds updated: {len(ready)}/{len(ids)}")
    if failures or len(ready) != len(ids):
        raise RuntimeError(f"Some backgrounds were deferred: {failures}")


if __name__ == "__main__":
    main()
