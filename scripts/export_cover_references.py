"""Export current Gündem publisher photos for an editorial image restyle.

Read-only: this script never changes Supabase or exports account data. Publication
gates are shared with the news pipeline. Missing current news stays missing.
"""
import argparse
import io
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from PIL import Image
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from event_images import MAX_BYTES, download
from pipeline_visibility import ready_event_ids
from popularity import POLICY, canonical_url, normalize, parse_time, read_all


def recent_events(db, now):
    cutoff = now - timedelta(hours=POLICY["event_window_hours"])
    rows = []
    # Fail closed if the export would need an unexpectedly large candidate set.
    for offset in range(0, 5000, 1000):
        page = (
            db.table("events")
            .select("id,title,summary,cover_image_url,created_at,enough_data,numeric_data,"
                    "source_count,popularity_score,popularity_updated_at")
            .gte("created_at", cutoff.isoformat())
            .lte("created_at", now.isoformat())
            .eq("enough_data", True)
            .order("id")
            .range(offset, offset + 999)
            .execute().data
        )
        rows.extend(page)
        if len(page) < 1000:
            return rows
    raise RuntimeError("Recent candidate limit exceeded; export stopped")


def recent_articles(articles, now):
    """Deduplicate before applying the window, matching the public feed."""
    cutoff = now - timedelta(hours=POLICY["event_window_hours"])
    valid = [article for article in articles
             if (at := parse_time(article.get("published_at"))) and at <= now]
    valid.sort(key=lambda article: (parse_time(article["published_at"]), int(article["id"])))
    seen_ids, seen_urls, seen_titles = set(), set(), set()
    result = []
    for article in valid:
        source = normalize(article.get("source"))
        title = normalize(article.get("title"))
        url = canonical_url(article.get("url"))
        title_key = (source, title)
        if (not source or article["id"] in seen_ids or (url and url in seen_urls)
                or (title and title_key in seen_titles)):
            continue
        seen_ids.add(article["id"])
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title_key)
        if parse_time(article["published_at"]) >= cutoff:
            result.append(article)
    return result


def select_current_events(db, now):
    events = recent_events(db, now)
    ids = [int(event["id"]) for event in events]
    analyses = read_all(db, "event_analyses", "event_id,status,analysis", "event_id", ids,
                        order_by="event_id")
    # Recompute source_count from linked current articles instead of trusting a
    # cached source count from the last six-hour pipeline execution.
    candidates = ready_event_ids([{**event, "source_count": 2} for event in events], analyses, now)
    links = read_all(db, "event_news", "event_id,news_id", "event_id", candidates, order_by="news_id")
    article_ids = sorted({int(link["news_id"]) for link in links})
    articles = read_all(db, "news", "id,title,source,url,published_at", "id", article_ids)
    by_id = {int(article["id"]): article for article in articles}
    linked = {event_id: [] for event_id in candidates}
    for link in links:
        article = by_id.get(int(link["news_id"]))
        if article is not None:
            linked[int(link["event_id"])].append(article)
    current = {event_id: recent_articles(items, now) for event_id, items in linked.items()}
    checked = [{**event, "source_count": len({normalize(article["source"])
                for article in current.get(int(event["id"]), [])})}
               for event in events if int(event["id"]) in current]
    selected = ready_event_ids(checked, analyses, now, limit=min(3, POLICY["primary_limit"]))
    events_by_id = {int(event["id"]): event for event in checked}
    return [(events_by_id[event_id], current[event_id]) for event_id in selected]


def export(db, output, now=None):
    now = now or datetime.now(timezone.utc)
    # A new directory prevents old images from leaking into a later empty export.
    output.mkdir(parents=True, exist_ok=False)
    selected = select_current_events(db, now)
    manifest = {
        "generated_at": now.isoformat(),
        "events": [],
        "reason": None if selected else "No current events pass the 36-hour, source, popularity and previous-year data gates.",
    }
    for event, articles in selected:
        entry = {
            "event_id": int(event["id"]),
            "title": event.get("title") or "",
            "summary": event.get("summary") or "",
            "original_image_url": event.get("cover_image_url"),
            "sources": [{"publisher": article.get("source"), "article_url": article.get("url")}
                        for article in articles],
            "source_filename": None,
        }
        try:
            if not entry["original_image_url"]:
                raise ValueError("No original publisher cover")
            data, mime = download(entry["original_image_url"], cap=MAX_BYTES)
            if not mime.lower().startswith("image/"):
                raise ValueError("Publisher response is not an image")
            with Image.open(io.BytesIO(data)) as original:
                extension = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(original.format)
                if extension is None or getattr(original, "is_animated", False):
                    raise ValueError("Unsupported original image format")
                original.verify()
            filename = f"event-{entry['event_id']}-original{extension}"
            (output / filename).write_bytes(data)
            entry["source_filename"] = filename
        except Exception as error:
            # Never log HTTP exception strings, client headers, or credentials.
            entry["image_status"] = "Original image unavailable; no substitute exported"
            print(f"Original unavailable | event={entry['event_id']} | {type(error).__name__}")
        manifest["events"].append(entry)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"Public cover references exported | events={len(selected)} | images={sum(bool(e['source_filename']) for e in manifest['events'])}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("cover-references"))
    args = parser.parse_args()
    try:
        db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
        export(db, args.output)
    except Exception as error:
        print(f"Read-only export failed | {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
