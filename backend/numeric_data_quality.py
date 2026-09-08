"""Require a sourced, observed previous-calendar-year baseline before publication.

Dates are read only from numeric point labels. A publication date, prose mention,
projection, missing value or categorical comparison cannot supply the baseline.
"""
import math
import re
from datetime import date, datetime, timezone
from urllib.parse import urlsplit


_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|"
    "ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"
)
_TIME_AXIS = re.compile(r"\b(year|years|month|months|date|time|quarter|annual|yearly|yıl|yıllar|yıllık|ay|aylar|tarih|zaman|çeyrek)\b", re.I)


def point_year(label):
    """Accept unambiguous calendar labels, not years embedded in arbitrary prose."""
    if not isinstance(label, str):
        return None
    label = label.strip()
    if re.fullmatch(r"[12]\d{3}", label):
        return int(label)
    match = re.fullmatch(r"([12]\d{3})-(\d{2})(?:-(\d{2}))?", label)
    if match:
        year, month, day = match.groups()
        try:
            return date(int(year), int(month), int(day or 1)).year
        except ValueError:
            return None
    if re.fullmatch(r"[12]\d{3}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", label):
        try:
            return datetime.fromisoformat(label.replace("Z", "+00:00")).year
        except ValueError:
            return None
    for pattern in (
        r"([12]\d{3})\s+Q[1-4]", r"Q[1-4]\s+([12]\d{3})",
        rf"([12]\d{{3}})\s+(?:{_MONTHS})", rf"(?:{_MONTHS})\s+([12]\d{{3}})",
        r"([12]\d{3})\s+[1-4]\.\s*çeyrek", r"[1-4]\.\s*çeyrek\s+([12]\d{3})",
    ):
        match = re.fullmatch(pattern, label, re.I)
        if match:
            return int(match.group(1))
    return None


def finite_point(point):
    if not isinstance(point, dict) or type(point.get("value")) not in (int, float):
        return False
    try:
        return math.isfinite(point["value"])
    except OverflowError:
        return False


def observed_point(point):
    return (finite_point(point) and point.get("is_projection") is not True
            and point.get("is_forecast") is not True
            and point.get("observation_type", "observed") == "observed"
            and (point.get("group") is None or isinstance(point["group"], str))
            and point_year(point.get("label")) is not None)


def source_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not any(char.isspace() for char in parsed.netloc))
    except ValueError:
        return False


def temporal_series(item):
    if not isinstance(item, dict):
        return False
    if item.get("ordered") is True or item.get("chart_type") == "line":
        return True
    axis = item.get("comparison_axis")
    if axis is None:
        axis = item.get("x_label", "")
    if isinstance(axis, str) and _TIME_AXIS.search(axis):
        return True
    points = item.get("points")
    return (isinstance(points, list) and len(points) >= 2
            and all(isinstance(p, dict) and point_year(p.get("label")) is not None for p in points))


def _valid_timeline(item, year):
    points = item.get("points")
    if not isinstance(points, list) or item.get("is_projection") is True or item.get("is_forecast") is True:
        return False
    observed = [p for p in points if observed_point(p)]
    return len(observed) >= 2 and any(point_year(p["label"]) == year for p in observed)


def valid_numeric_data(series, now=None):
    """Every chronological research series must contain last year's actual data."""
    if not isinstance(series, list):
        return False
    year = (now or datetime.now(timezone.utc)).year - 1
    timelines = [item for item in series if temporal_series(item)]
    return bool(timelines) and all(source_url(item.get("source_url")) and _valid_timeline(item, year)
                                   for item in timelines)


def valid_analysis_timeline(analysis, series, now=None):
    """The displayed timeline must retain a previous-year point from its source."""
    if not valid_numeric_data(series, now) or not isinstance(analysis, dict):
        return False
    charts = analysis.get("charts")
    if not isinstance(charts, list):
        return False
    year = (now or datetime.now(timezone.utc)).year - 1
    timelines = [chart for chart in charts if temporal_series(chart)]
    if not timelines:
        return False
    for chart in timelines:
        urls = chart.get("source_urls")
        if not isinstance(urls, list) or not _valid_timeline(chart, year):
            return False
        research_points = {
            (p["label"].strip(), p["value"], p.get("group") or "")
            for item in series if temporal_series(item) and item.get("source_url") in urls
            for p in item["points"] if observed_point(p) and point_year(p["label"]) == year
        }
        if not any((p["label"].strip(), p["value"], p.get("group") or "") in research_points
                   for p in chart["points"] if observed_point(p) and point_year(p["label"]) == year):
            return False
    return True
