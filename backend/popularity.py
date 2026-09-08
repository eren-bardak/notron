"""Repeat-safe popularity: each original contribution ages independently."""
import json
import math
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

POLICY = json.loads((Path(__file__).resolve().parents[1] / 'config/popularity.json').read_text())


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def normalize(value):
    value = unicodedata.normalize('NFKD', str(value or '').casefold())
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).replace('ı', 'i').split())


def source_side(value):
    value = normalize(value)
    for side, names in {'left': {'l', 'left', 'sol'}, 'center': {'c', 'center', 'centre', 'merkez'}, 'right': {'r', 'right', 'sag'}}.items():
        if value in names:
            return side
    return None


def decay(at, now):
    if at is None or at > now:
        return 0.0
    hours = (now - at).total_seconds() / 3600
    return 2 ** (-hours / POLICY['half_life_hours'])


def current_score(event, now):
    try:
        score = float(event.get('popularity_score') or 0)
    except (ValueError, TypeError):
        return 0.0
    if not math.isfinite(score) or score < 0:
        return 0.0
    return score * decay(parse_time(event.get('popularity_updated_at')), now)


def canonical_url(value):
    try:
        url = urlsplit(value or '')
        if url.scheme not in {'http', 'https'} or not url.netloc:
            return ''
        params = [(k, v) for k, v in parse_qsl(url.query) if not k.startswith('utm_') and k not in {'fbclid', 'gclid'}]
        return urlunsplit((url.scheme, url.netloc.lower(), url.path, urlencode(sorted(params)), ''))
    except ValueError:
        return ''


def question_ids(analysis):
    """Match the frontend's wording fingerprints; unrelated JSON keys are not votes."""
    result = set()
    questions = analysis.get('binary_questions') if isinstance(analysis, dict) else None
    if not isinstance(questions, list):
        return result
    questions = [q for q in questions if isinstance(q, dict) and isinstance(q.get("question"), str) and q["question"].strip()][:3]
    for index, question in enumerate(questions):
        text = question.get('question', '') if isinstance(question, dict) else ''
        if not isinstance(text, str) or not text.strip():
            continue
        labels = question.get("choice_labels")
        modern = isinstance(labels, dict) and all(isinstance(labels.get(k), str) and labels[k].strip() for k in ("yes", "no", "unsure"))
        if modern:
            text = "\x1f".join([text, labels["yes"], labels["no"], labels["unsure"], question.get("data_anchor") if isinstance(question.get("data_anchor"), str) else ""])
        value = 2166136261
        for char in text:
            code = ord(char)
            if not modern and code > 0xFFFF:
                code = 0xD800 + ((code - 0x10000) >> 10)
            value = ((value ^ code) * 16777619) & 0xFFFFFFFF
        digits = ''
        while value:
            value, remainder = divmod(value, 36)
            digits = '0123456789abcdefghijklmnopqrstuvwxyz'[remainder] + digits
        result.add(f'{"n4" if modern else "n3"}_{digits or "0"}_{index}')
    return result


def scored_people(rows, now, valid):
    """One scored contribution per person and event in each contribution type."""
    first = {}
    for row in rows:
        at = parse_time(row.get('created_at'))
        user = row.get('user_id')
        if not user or not at or at > now or not valid(row):
            continue
        if user not in first or at < first[user]:
            first[user] = at
    return sum(decay(at, now) for at in first.values()), len(first)


def score_event(event, links, news_by_id, sides, micro, comments, answers, analysis, now):
    event_id = int(event['id'])
    articles = []
    for link in links:
        if int(link['event_id']) != event_id:
            continue
        article = news_by_id.get(int(link['news_id']))
        if not article:
            continue
        published = parse_time(article.get('published_at'))
        # News ages from publication, never from the time a batch happens to run.
        if not published or published > now or not normalize(article.get('source')):
            continue
        articles.append((published, article))
    seen_ids, seen_urls, seen_titles = set(), set(), set()
    article_score = 0.0
    group_first = {}
    publisher_first = {}
    recent_sources = set()
    side_sources = {'left': set(), 'center': set(), 'right': set()}
    cutoff = now - timedelta(hours=POLICY['event_window_hours'])
    for at, article in sorted(articles, key=lambda pair: (pair[0], int(pair[1]['id']))):
        source = normalize(article.get('source'))
        url = canonical_url(article.get('url'))
        title = normalize(article.get('title'))
        title_key = (source, title)
        if article['id'] in seen_ids or (url and url in seen_urls) or (title and title_key in seen_titles):
            continue
        seen_ids.add(article['id'])
        if url:
            seen_urls.add(url)
        if title:
            seen_titles.add(title_key)
        article_score += POLICY['article_points'] * decay(at, now)
        if source in sides and source not in publisher_first:
            publisher_first[source] = at
        side = sides.get(source)
        if side and side not in group_first:
            group_first[side] = at
        if at >= cutoff:
            recent_sources.add(source)
            if side:
                side_sources[side].add(source)
    group_times = sorted(group_first.values())
    cross_at = group_times[1] if len(group_times) >= 2 else None
    bonus = POLICY['cross_group_points'] * decay(cross_at, now)
    # Each registered publisher earns a one-time breadth contribution after the first.
    # Age from its first article, never a rerun or a later repost. Ownership is unknown.
    breadth_times = sorted(publisher_first.values())[1:1 + POLICY["publisher_breadth_cap"]]
    breadth = POLICY["publisher_breadth_points"] * sum(decay(at, now) for at in breadth_times)
    own = lambda rows: [r for r in rows if int(r['event_id']) == event_id]
    micro_score, micro_count = scored_people(own(micro), now, lambda r: r.get('status') == 'active' and bool(str(r.get('text') or '').strip()))
    writer_score, writer_count = scored_people(own(comments), now, lambda r: r.get('status') == 'active' and r.get('author_role') == 'writer' and bool(str(r.get('text') or '').strip()))
    valid_ids = question_ids(analysis)
    def has_vote(row):
        values = row.get('binary_answers')
        return isinstance(values, dict) and any(isinstance(values.get(key), str) and values[key] in {'yes', 'no', 'unsure'} for key in valid_ids)
    vote_score, vote_count = scored_people(own(answers), now, has_vote)
    score = article_score + bonus + breadth + POLICY['participation_points'] * (micro_score + vote_score) + POLICY['writer_points'] * writer_score
    return {'score': score, 'source_count': len(recent_sources), 'side_sources': side_sources,
            'micro_count': micro_count, 'writer_count': writer_count, 'vote_count': vote_count,
            'publisher_breadth_score': breadth,
            'cross_group_at': cross_at.isoformat() if cross_at else None}


def read_all(db, table, columns, filter_column=None, ids=None, order_by="id"):
    """Paginate both IDs and results; a failed read must abort scoring."""
    if ids is not None and not ids:
        return []
    batches = [None] if ids is None else [ids[i:i+100] for i in range(0, len(ids), 100)]
    rows = []
    for batch in batches:
        offset = 0
        while True:
            query = db.table(table).select(columns)
            if batch is not None:
                query = query.in_(filter_column, batch)
            page = query.order(order_by).range(offset, offset + 999).execute().data
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += len(page)
    return rows
