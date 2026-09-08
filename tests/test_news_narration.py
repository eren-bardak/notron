import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from news_narration import featured_ids, narration_text, refresh_narrations, text_signature


class NarrationTests(unittest.TestCase):
    def test_only_featured_three_no_other_events(self):
        feed = {"events": [{"id": i} for i in [75, 76, 77, 81]], "otherEvents": [{"id": 82}]}
        self.assertEqual(featured_ids(feed), [75, 76, 77])

    def test_reads_existing_copy_in_order_and_changes_cache_on_edits(self):
        story = {"card_headline": " Yeni karar. ", "card_summary": "Meclis   oy verdi.",
                 "background": {"narration": "Önceki karar ertelendi."}, "card_question_bridge": "Şimdi:", "cover_question": "Hız mı, uzlaşma mı?"}
        text = narration_text(story)
        self.assertEqual(text, "Yeni karar.\n\nMeclis oy verdi.\n\nÖnceki karar ertelendi.\n\nŞimdi: Hız mı, uzlaşma mı?")
        self.assertNotEqual(text_signature(text), text_signature(text + " Yeni bilgi."))

    def test_cached_audio_does_not_call_provider_or_mutate_ballots(self):
        story = {"card_headline": "Haber başlığı.", "card_summary": "Olayın kısa açıklaması.", "binary_questions": [{"id": "existing-vote"}]}
        text = narration_text(story)
        story["card_narration"] = {"signature": text_signature(text), "url": "https://example.invalid/audio.mp3"}
        class Query:
            def table(self,*_): return self
            def select(self,*_): return self
            def in_(self,*_): return self
            def eq(self,*_): return self
            def execute(self): return SimpleNamespace(data=[{"event_id":75,"analysis":story}])
            def update(self,*_): raise AssertionError("Cache hit must not write")
        result = refresh_narrations(Query(), None, [75])
        self.assertEqual(result[0]["status"], "cached")
        self.assertEqual(story["binary_questions"], [{"id":"existing-vote"}])


if __name__ == "__main__":
    unittest.main()
