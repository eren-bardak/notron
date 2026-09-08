import html
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from supabase import create_client


def recent_news_cutoff(now=None):
    """Return the inclusive UTC cutoff for current news."""

    current_time = now or datetime.now(timezone.utc)
    return current_time - timedelta(hours=NEWS_WINDOW_HOURS)


def recent_rss_published_at(entry, now=None):
    """Return an RSS publication time only when it is inside the window."""

    current_time = now or datetime.now(timezone.utc)
    parsed_date = entry.get("published_parsed")

    # Undated and update-only entries cannot prove when they were published.
    if not parsed_date:
        return None

    try:
        published_at = datetime(
            *parsed_date[:6],
            tzinfo=timezone.utc,
        )
    except (TypeError, ValueError):
        return None

    cutoff = recent_news_cutoff(current_time)

    if not cutoff <= published_at <= current_time:
        return None

    return published_at

def clean_description(value):
    """Remove HTML tags from RSS descriptions."""

    if not isinstance(value, str):
        return None

    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = " ".join(value.split()).strip()

    return value[:2000] or None
# ============================================================
# CONFIG
# ============================================================

NEWS_WINDOW_HOURS = 36
MAX_PAGE_SCRAPES_PER_SOURCE = 5

load_dotenv()

supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY"),
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Safari/537.36"
    )
}

now = datetime.now(timezone.utc)


def valid_image_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def image_from_rss(entry):
    """Use the cover already included in the RSS entry."""

    for field in ("media_content", "media_thumbnail"):
        for image in entry.get(field, []):
            url = image.get("url")
            if valid_image_url(url):
                return url

    for enclosure in entry.get("enclosures", []):
        url = enclosure.get("href") or enclosure.get("url")
        if str(enclosure.get("type", "")).startswith("image/") and valid_image_url(url):
            return url

    return None


def image_from_article(article_url):
    """Fallback to the article's og:image or twitter:image."""

    try:
        response = requests.get(article_url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        for selector in (
            'meta[property="og:image"]',
            'meta[property="og:image:url"]',
            'meta[name="twitter:image"]',
        ):
            tag = soup.select_one(selector)
            image = tag.get("content") if tag else None
            image = urljoin(article_url, image) if image else None
            if valid_image_url(image):
                return image
    except requests.RequestException:
        pass

    return None


# ============================================================
# SOURCES
# ============================================================

sources = (
    supabase.table("sources")
    .select("name,source_group,rss_url")
    .eq("active", True)
    .execute()
    .data
)

print("\n================================")
print("NEWS SENSOR")
print("================================")
print(f"Active sources: {len(sources)}")
print(f"Window: last {NEWS_WINDOW_HOURS} hours")


# ============================================================
# FETCH
# ============================================================

total_signals = 0
total_inserted = 0
total_duplicates = 0
working_sources = 0


for source in sources:

    name = source["name"]
    group = source["source_group"]
    rss_url = source["rss_url"]
    page_scrapes = 0

    print(f"\n[{group}] {name}")

    try:

        response = requests.get(
            rss_url,
            headers=HEADERS,
            timeout=20,
        )

        response.raise_for_status()

        feed = feedparser.parse(
            response.content
        )

        recent_count = 0

        for article in feed.entries:

            title = article.get("title")
            url = article.get("link")
            description = clean_description(
                article.get("summary")
                or article.get("description")
            )

            if not title or not url:
                continue

            title = title.strip()
            url = url.strip()

            published_at = recent_rss_published_at(
                article,
                now,
            )

            if published_at is None:
                continue

            recent_count += 1
            total_signals += 1

            # Keep previously processed rows unchanged. A genuinely new URL is
            # inserted below and receives a fresh database-generated ID.
            existing = (
                supabase.table("news")
                .select("id")
                .eq("url", url)
                .limit(1)
                .execute()
                .data
            )

            if existing:
                total_duplicates += 1
                continue

            cover_image_url = image_from_rss(article)

            if not cover_image_url and page_scrapes < MAX_PAGE_SCRAPES_PER_SOURCE:
                cover_image_url = image_from_article(url)
                page_scrapes += 1

            news_data = {
                "title": title,
                "source": name,
                "url": url,
                "country": "TR",
                "published_at": published_at.isoformat(),
                "description": description,
                "content_type": "rss",
                "clustered_at": None,
            }

            if cover_image_url:
                news_data["cover_image_url"] = cover_image_url

            supabase.table("news").insert(news_data).execute()
            total_inserted += 1

        if recent_count > 0:
            working_sources += 1

        print(
            f"Last {NEWS_WINDOW_HOURS}h: {recent_count}"
        )

    except Exception as e:

        print(
            f"ERROR: {type(e).__name__}: {e}"
        )


# ============================================================
# SUMMARY
# ============================================================

print("\n================================")
print("FETCH FINISHED")
print("================================")

print(
    f"Working sources, How many sources have at least one working article / Number of sources: "
    f"{working_sources}/{len(sources)}"
)

print(
    f"Current RSS article signals: {total_signals}"
)

print(f"New articles inserted: {total_inserted}")
print(f"Duplicate URLs skipped: {total_duplicates}")
