"""Read-only export of public event evidence and questions; no participant data."""
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from supabase import create_client
from editorial_quality import current_editorial
from popularity import POLICY, parse_time, read_all
from pipeline_visibility import ready_event_ids


def main():
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=POLICY["event_window_hours"])
    rows = read_all(db, "events", "id,title,created_at,enough_data,numeric_data,source_count,popularity_score,popularity_updated_at,is_visible")
    events = [e for e in rows if (at := parse_time(e.get("created_at"))) and cutoff <= at <= now]
    analyses = read_all(db, "event_analyses", "event_id,status,analysis,research,generated_at", "event_id", [e["id"] for e in events], order_by="event_id")
    by_id = {int(row["event_id"]): row for row in analyses}
    visible = ready_event_ids(events, analyses, now)
    result = []
    for event in events:
        row = by_id.get(int(event["id"]), {})
        analysis = row.get("analysis") or {}
        result.append({"event_id": event["id"], "title": event["title"], "status": row.get("status"),
                       "published": event["id"] in visible, "stored_visible": event.get("is_visible"), "generated_at": row.get("generated_at"), "research_revision": (row.get("research") or {}).get("editorial_revision"), "editorial_current": current_editorial(analysis),
                       "review": analysis.get("editorial_review"), "explanation": analysis.get("event_explanation"),
                       "charts": analysis.get("charts"), "questions": analysis.get("binary_questions")})
    output = Path("editorial-review.json")
    output.write_text(json.dumps({"generated_at": now.isoformat(), "published_ids": visible, "events": result}, ensure_ascii=False, indent=2) + "\n")
    print(f"Editorial export | published={len(visible)} | reviewed={sum(e['editorial_current'] for e in result)}")


if __name__ == "__main__":
    main()
