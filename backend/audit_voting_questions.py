"""Offline, read-only audit of editorial-review exports or event_analyses rows.

Usage: python backend/audit_voting_questions.py export.json --event-id 513 --event-id 517
No database access, generation, inferred completion, or ballot changes.
"""
import argparse
import json
from pathlib import Path

from deep_dive.models import complete_question_text


def audit_questions(document, event_ids=None):
    rows = document.get("events", []) if isinstance(document, dict) else document
    if not isinstance(rows, list):
        raise ValueError("Expected an events export or a list of event_analyses rows")
    selected = set(event_ids) if event_ids else None
    findings = []
    checked = 0
    for row in sorted(rows, key=lambda row: int(row["event_id"])):
        event_id = int(row["event_id"])
        if selected is not None and event_id not in selected:
            continue
        questions = row.get("questions") if "questions" in row else (row.get("analysis") or {}).get("binary_questions")
        if not isinstance(questions, list) or not questions:
            findings.append({"event_id": event_id, "reason": "missing_question_array"})
            continue
        for index, question in enumerate(questions):
            checked += 1
            text = question.get("question") if isinstance(question, dict) else None
            if complete_question_text(text):
                continue
            findings.append({
                "event_id": event_id, "question_index": index,
                "reason": "incomplete_or_invalid_question", "question": text,
                "characters": len(text) if isinstance(text, str) else None,
                "utf16_units": len(text.encode("utf-16-le")) // 2 if isinstance(text, str) else None,
                "choice_labels": question.get("choice_labels") if isinstance(question, dict) else None,
                "label_review": "Review all labels against recovered question; grammatical completeness requires editorial review.",
            })
    return {"dry_run": True, "checked_questions": checked, "findings": findings,
            "repair_policy": "Recover original complete text from provenance; do not infer missing endings or alter votes. Any changed question, label or anchor requires a new ballot fingerprint; retain historical answers under their original IDs."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--event-id", type=int, action="append")
    args = parser.parse_args()
    result = audit_questions(json.loads(args.input.read_text()), args.event_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
