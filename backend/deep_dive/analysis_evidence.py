"""Select immutable research evidence instead of asking the writer to retype it."""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, StrictInt, create_model

from .models import Chart, EventAnalysis, StorySection
from numeric_data_quality import point_year, temporal_series, valid_analysis_timeline


def evidence_catalog(research):
    return {
        f"series_{i}": {
            **series.model_dump(mode="json"),
            "point_indices": list(range(len(series.points))),
        }
        for i, series in enumerate(research.numeric_series)
    }


def analysis_output_model(research):
    """Constrain citations to known URLs and charts to known series selections."""
    urls = list(dict.fromkeys(
        [item.url for item in research.evidence]
        + ([item.source_url for item in research.numeric_series]
           + [item.source_url for item in research.metric_candidates]
           if research.numeric_series else [])
    ))
    if not urls:
        raise ValueError("Analysis needs supplied source URLs")
    cited_section = create_model(
        "CitedStorySection", __base__=StorySection,
        source_urls=(list[Literal[tuple(urls)]], Field(min_length=1)),
    )
    # Preserve prose/display metadata, but never ask the model to copy data fields.
    chart_fields = {
        name: (field.annotation, deepcopy(field))
        for name, field in Chart.model_fields.items()
        if name not in {"points", "unit", "source_urls"}
    }
    series_ids = tuple(evidence_catalog(research)) or ("none",)
    chart_selection = create_model(
        "ChartSelection", **chart_fields,
        source_series=(Literal[series_ids], ...),
        point_indices=(list[StrictInt], Field(min_length=1, max_length=24)),
    )
    return create_model(
        "EvidenceSelectedAnalysis", __base__=EventAnalysis,
        background=(cited_section, ...), event_explanation=(cited_section, ...),
        charts=(list[chart_selection], Field(
            min_length=1 if research.numeric_series else 0,
            max_length=2 if research.numeric_series else 0,
        )),
    )


def materialize_analysis(draft, research):
    """Resolve selections, then reject charts that omit required evidence."""
    data = draft.model_dump(mode="json")
    catalog = evidence_catalog(research)
    for i, chart in enumerate(data["charts"]):
        series_id = chart.pop("source_series")
        chart.pop("point_indices")
        # Validate before JSON serialization can coerce an invalid bool to an int.
        indices = list(draft.charts[i].point_indices)
        series = catalog.get(series_id)
        if series is None:
            raise ValueError(f"Chart {i}: select an existing source_series")
        if (not 1 <= len(indices) <= 24
                or any(type(index) is not int or index < 0 or index >= len(series["points"])
                       for index in indices)
                or len(set(indices)) != len(indices)):
            raise ValueError(f"Chart {i}: use distinct point_indices from 0 to {len(series['points']) - 1}")
        if series["ordered"]:
            indices = sorted(indices)
        chart.update(
            unit=series["unit"], source_urls=[series["source_url"]],
            points=[deepcopy(series["points"][index]) for index in indices],
            x_label=series["comparison_axis"],
        )
        if not valid_analysis_timeline({"charts": [chart]}, [series]):
            year = datetime.now(timezone.utc).year - 1
            baseline = [index for index, point in enumerate(series["points"])
                        if point_year(point["label"]) == year]
            hint = (f" Include the observed {year} baseline: point_indices {baseline}."
                    if temporal_series(chart) else "")
            raise ValueError(
                f"Chart {i} ({series_id}) failed evidence validation.{hint} "
                "Select a valid display: metric needs exactly one point; timelines need "
                "at least two observed dated points and the prior-year baseline."
            )
    return EventAnalysis.model_validate(data)
