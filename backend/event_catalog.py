"""V1.1 event categories and cross-spectrum source eligibility."""
import json
from pathlib import Path
from popularity import normalize, canonical_url

CATEGORIES = json.loads((Path(__file__).resolve().parents[1] / 'config/categories.json').read_text())
CATEGORY_IDS = {row['id'] for row in CATEGORIES}


def category_id(value, title=''):
    if value in CATEGORY_IDS or value == 'general':
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
        ('politics', ('tbmm', 'cumhurbaskani', 'bakan', 'belediye baskani', 'secim', 'chp', 'akp', 'ak parti', 'anayasa', 'meclis', 'disisleri', 'koalisyon')),
    ):
        if any(term in words for term in terms):
            return category
    # Unclassified general news stays in Gündem without inventing a seventh tab.
    return 'general'


def balanced_articles(articles, sides, category="politics", title=""):
    """Require two publishers; cross-spectrum coverage earns a score bonus."""
    groups, seen_urls, seen_titles, publishers = set(), set(), set(), set()
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
        publishers.add(source)
        groups.add(sides.get(source))
    return len(publishers) >= 2


def balanced_event(event):
    return (event.get('source_count') or 0) >= 2
