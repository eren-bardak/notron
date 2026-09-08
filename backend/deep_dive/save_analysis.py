from .models import EventAnalysis, ResearchBundle


def save_analysis(db, research: ResearchBundle, analysis: EventAnalysis) -> None:
    """Keep the newest research and cinematic analysis for an event."""
    numeric_data = [
        series.model_dump(mode="json")
        for series in research.numeric_series
    ]

    research_data = research.model_dump(mode="json")
    analysis_data = analysis.model_dump(mode="json")
    base_row = {
        "event_id": analysis.event_id,
        "status": "ready",
        "research": research_data,
        "analysis": analysis_data,
        "generated_at": analysis.generated_at,
    }
    rich_row = {
        **base_row,
        "numeric_evidence": {
            "metrics": research_data["metric_candidates"],
            "series": research_data["numeric_series"],
        },
        "data_story": analysis_data["data_story"],
        "data_questions": analysis_data["binary_questions"],
        "evidence_count": len(research.evidence),
        "metric_count": len(research.metric_candidates),
        "data_point_count": sum(len(series.points) for series in research.numeric_series),
    }

    try:
        db.table("event_analyses").upsert(
            rich_row,
            on_conflict="event_id",
        ).execute()
    except Exception:
        # The full JSON remains available while an older database waits for
        # the event-analyses data-story migration.
        db.table("event_analyses").upsert(
            base_row,
            on_conflict="event_id",
        ).execute()

    # Publish the data flag only after the complete analysis is safely stored.
    db.table("events").update(
        {
            "background": research.background,
            "background_sources": [
                evidence.url
                for evidence in research.evidence
                if evidence.url
            ],
            "numeric_data": numeric_data,
            "enough_data": bool(numeric_data),
            "problem_supported": research.problem_supported,
            "central_problem": research.central_problem,
        }
    ).eq("id", analysis.event_id).execute()
