"""Optional event highlights. They never determine publication eligibility."""
from copy import deepcopy
from math import isfinite
from urllib.parse import urlsplit

from pydantic import ValidationError

from .models import KeyMetric

KEY_METRICS_REVISION = 1


def source_url(value):
    try:
        url = urlsplit(value or "")
        return value if url.scheme in ("http", "https") and url.hostname and url.username is None and not any(char.isspace() for char in value) else None
    except (TypeError, ValueError):
        return None


def grounded_key_metrics(selected, research):
    """Keep at most three distinct, unchanged research-backed selections."""
    if not isinstance(research, dict) or not isinstance(selected, list):
        return []
    def items(key):
        value = research.get(key)
        return value if isinstance(value, list) else []
    sources = {item.get("url") for item in items("evidence") if isinstance(item, dict) and isinstance(item.get("url"), str)}
    sources.update(item.get("source_url") for item in items("numeric_series") if isinstance(item, dict) and isinstance(item.get("source_url"), str))
    candidates = []
    for item in items("metric_candidates"):
        try:
            metric = KeyMetric.model_validate(item).model_dump(mode="json")
        except (ValidationError, TypeError, ValueError):
            continue
        if not all(metric[key].strip() for key in ("label", "unit", "time_scope", "geography", "why_it_matters", "source_name")):
            continue
        if not source_url(metric["source_url"]) or metric["source_url"] not in sources:
            continue
        if any(metric[key] is not None and not isfinite(metric[key]) for key in ("comparison_value", "delta_percent")):
            continue
        candidates.append(metric)
    kept, seen = [], set()
    for item in selected:
        try:
            metric = KeyMetric.model_validate(item).model_dump(mode="json")
        except (ValidationError, TypeError, ValueError):
            continue
        if metric not in candidates:
            continue
        identity = tuple(str(metric[key]).strip().casefold() for key in ("label", "value", "unit", "time_scope", "geography"))
        if identity in seen:
            continue
        seen.add(identity)
        kept.append(metric)
        if len(kept) == 3:
            break
    return kept


def with_key_metrics(analysis, research):
    """Normalize legacy caches without touching questions, covers or research."""
    result = deepcopy(analysis or {})
    story = result.get("data_story")
    if isinstance(story, dict):
        story["key_metrics"] = grounded_key_metrics(story.get("key_metrics"), research)
    result["key_metrics_revision"] = KEY_METRICS_REVISION
    return result


def refresh_key_metrics(db, event_ids):
    if not event_ids:
        return 0
    rows = db.table("event_analyses").select("event_id,status,analysis,research").in_("event_id", event_ids).execute().data
    updated = 0
    for row in rows:
        old = row.get("analysis") or {}
        if row.get("status") != "ready" or old.get("key_metrics_revision") == KEY_METRICS_REVISION:
            continue
        analysis = with_key_metrics(old, row.get("research") or {})
        db.table("event_analyses").update({"analysis": analysis}).eq("event_id", row["event_id"]).execute()
        updated += 1
    return updated
