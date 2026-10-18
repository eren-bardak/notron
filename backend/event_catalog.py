"""V1.1 event categories and cross-spectrum source eligibility."""
import json
from pathlib import Path
from popularity import normalize, canonical_url

CATEGORIES = json.loads((Path(__file__).resolve().parents[1] / 'config/categories.json').read_text())
CATEGORY_IDS = {row['id'] for row in CATEGORIES}


def category_id(value, title=''):
    if value in CATEGORY_IDS:
        return value
    aliases = {'economy': 'finance', 'technology_science': 'technology', 'culture': 'entertainment'}
    if value in aliases:
        return aliases[value]
    words = normalize(title)
    for category, terms in (
        ('sports', ('futbol', 'basketbol', 'galatasaray', 'fenerbahce', 'besiktas', 'sampiyon', 'super lig')),
        ('technology', ('yapay zeka', 'teknoloji', 'uzay', 'yazilim', 'bilim', 'uydu')),
        ('finance', ('enflasyon', 'faiz', 'borsa', 'dolar', 'butce', 'ucret', 'ekonomi', 'ihracat')),
        ('magazine', ('magazin', 'bosandi', 'evlendi', 'unlu oyuncu')),
        ('entertainment', ('konser', 'festival', 'sinema', 'muzik', 'tiyatro', 'dizi')),
    ):
        if any(term in words for term in terms):
            return category
    # Siyaset also covers public affairs, institutions, justice and public safety.
    return 'politics'


def balanced_articles(articles, sides):
    """Require distinct, deduplicated publishers on both the left and right."""
    groups, seen_urls, seen_titles = set(), set(), set()
    for article in articles:
        source = normalize(article.get('source'))
        url = canonical_url(article.get('url'))
        title = normalize(article.get('title'))
        title_key = (source, title)
        if not source or (url and url in seen_urls) or (title and title_key in seen_titles):
            continue
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title_key)
        groups.add(sides.get(source))
    return {'left', 'right'} <= groups


def balanced_event(event):
    return ((event.get('source_count') or 0) >= 2
            and (event.get('left_source_count') or 0) > 0
            and (event.get('right_source_count') or 0) > 0)
