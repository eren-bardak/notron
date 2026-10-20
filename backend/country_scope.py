"""Require explicit, source-grounded country relevance, never publisher geography."""
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field


class CountryEvidence(BaseModel):
    article_id: int = Field(gt=0)
    quote: str = Field(min_length=12, max_length=280)


class CountryScope(BaseModel):
    revision: Literal[1] = 1
    country: Literal['TR']
    relationship: Literal['domestic', 'direct_impact', 'unrelated']
    reason: str = Field(min_length=30, max_length=400)
    evidence: list[CountryEvidence] = Field(max_length=4)


def clean(value):
    return ' '.join(unicodedata.normalize('NFKC', value).split()) if isinstance(value, str) else ''


def country_eligible(event, country='TR', articles=None):
    metadata = event.get('data')
    if not isinstance(metadata, dict) or metadata.get('publication_excluded_reason'):
        return False
    scope = metadata.get('country_scope')
    if not isinstance(scope, dict):
        return False
    if (type(scope.get('revision')) is not int or scope.get('revision') != 1 or scope.get('country') != country
            or scope.get('relationship') not in ('domestic', 'direct_impact')
            or len(clean(scope.get('reason'))) < 30):
        return False
    evidence = scope.get('evidence')
    if not isinstance(evidence, list) or not 2 <= len(evidence) <= 4:
        return False
    ids, publishers = set(), set()
    originals = {row['id']: row for row in articles} if articles is not None else None
    for item in evidence:
        if not isinstance(item, dict):
            return False
        article_id, quote = item.get('article_id'), clean(item.get('quote'))
        if type(article_id) is not int or article_id <= 0 or article_id in ids or not 12 <= len(quote) <= 280:
            return False
        ids.add(article_id)
        if originals is not None:
            row = originals.get(article_id)
            if not row or quote not in clean(f"{row.get('title') or ''} {row.get('description') or row.get('summary') or ''}"):
                return False
            publisher = clean(row.get('source')).casefold()
            if not publisher:
                return False
            publishers.add(publisher)
    return originals is None or len(publishers) >= 2
