import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from editorial_quality import current_editorial
from popularity import question_ids


class EditorialQualityTests(unittest.TestCase):
    def test_legacy_and_failed_reviews_require_refresh(self):
        review = {"revision": 2, "question_intent": "event_implication", "event_specific": True, "matches_displayed_evidence": True,
                  "evidence_relevant": True, "not_factual_recall": True}
        self.assertTrue(current_editorial({"editorial_review": review}))
        for old in (None, {}, {"editorial_review": None}, {"editorial_review": {"revision": 0}}):
            self.assertFalse(current_editorial(old))
        for key in ("event_specific", "matches_displayed_evidence", "evidence_relevant", "not_factual_recall"):
            self.assertFalse(current_editorial({"editorial_review": {**review, key: False}}))

    def test_updated_question_does_not_reuse_old_ballot(self):
        old = {"binary_questions": [{"question": "2025 bütçesi nasıl değişti?", "question_type": "metric",
               "data_anchor": "2024: 5,5; 2025: 9 milyar TL", "choice_labels": {"yes": "Arttı", "no": "Azaldı", "unsure": "Belirsiz"}}]}
        new = {"binary_questions": [{"question": "Üsküdar'daki oy dengesi yönetimi uzlaşmaya iter mi?", "question_type": "metric",
               "data_anchor": "Son tur: 23 ve 19 oy", "choice_labels": {"yes": "Uzlaşmayı teşvik eder", "no": "Karar almayı zorlaştırır", "unsure": "Henüz belirsiz"}}]}
        self.assertTrue(set(question_ids(old)).isdisjoint(question_ids(new)))


if __name__ == "__main__":
    unittest.main()
