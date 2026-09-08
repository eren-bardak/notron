"""Version the editorial rules independently of question/answer fingerprints."""
RESEARCH_REVISION = 1
EDITORIAL_REVISION = 2


def current_editorial(analysis):
    review = analysis.get("editorial_review") if isinstance(analysis, dict) else None
    return (isinstance(review, dict) and review.get("revision") == EDITORIAL_REVISION
            and all(review.get(key) is True for key in (
                "event_specific", "matches_displayed_evidence", "evidence_relevant", "not_factual_recall"))
            and review.get("question_intent") in {"event_implication", "conditional_outlook"})
