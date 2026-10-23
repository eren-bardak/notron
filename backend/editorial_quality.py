"""Version the editorial rules independently of question/answer fingerprints."""
RESEARCH_REVISION = 1
EDITORIAL_REVISION = 2


def current_editorial(analysis):
    review = analysis.get("editorial_review") if isinstance(analysis, dict) else None
    return (isinstance(review, dict) and review.get("revision") == EDITORIAL_REVISION
            and all(review.get(key) is True for key in (
                "event_specific", "matches_displayed_evidence", "evidence_relevant", "not_factual_recall"))
            and review.get("question_intent") in ("event_implication", "conditional_outlook"))


def publication_quality(analysis):
    """Require a reviewed public consequence and substantive, distinct story/context."""
    if not isinstance(analysis, dict):
        return False
    review = analysis.get('publication_review') or {}
    if (review.get('revision') != 1 or review.get('newsworthy') is not True
            or review.get('basis') not in {'public_impact', 'institutional_decision', 'major_result', 'cultural_significance', 'accountability', 'scientific_development'}
            or len(str(review.get('reason') or '').strip()) < 30):
        return False
    sections = [analysis.get(key) or {} for key in ('background', 'event_explanation')]
    texts = [' '.join(str(section.get('narration') or '').split()) for section in sections]
    return bool(texts[0] and texts[1]) and texts[0].casefold() != texts[1].casefold()
