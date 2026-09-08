import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from deep_dive.cover_question import CoverQuestion, cover_patch, refresh_cover_questions, valid_cover_question


class CoverQuestionTests(unittest.TestCase):
    def setUp(self):
        self.research = {'evidence': [{'url': 'https://official.invalid/burs', 'finding': 'Yeni burs başvuruları açıldı.'}]}
        self.result = CoverQuestion(question='Yeni burslar kimlerin önünü açabilir?', what_happened='Kurum, yeni burs programı için başvuruları açtı.', question_bridge='Öğrencilerin desteğe erişimi açısından:', source_urls=['https://official.invalid/burs'], evidence_basis='Burs başvurularının kapsamı ve başvuru koşulları açıklanmıştır.')

    def test_format_and_sources(self):
        self.assertTrue(valid_cover_question(self.result.question))
        for text in ['Şok karar herkesi nasıl etkileyecek?', 'Sence?', 'Ne oldu? Kim yaptı?', '<b>Bu karar</b> neyi değiştirecek?', 'Bu karar neyi değiştirecek!']:
            self.assertFalse(valid_cover_question(text))
        self.assertEqual(cover_patch(self.result, self.research)['cover_question_revision'], 1)
        with self.assertRaises(ValueError):
            cover_patch(self.result, {'evidence': []})

    def test_cover_refresh_preserves_ballots_and_other_analysis_fields(self):
        original = {'binary_questions': [{'id': 'n4_existing', 'question': 'Önce hangi destek?'}], 'charts': [{'points': [1, 2]}], 'image_selection': {'url': 'photo'}}
        row = {'event_id': 7, 'analysis': original, 'research': self.research, 'generated_at': '2026-09-08T00:00:00Z'}
        writes = []
        class Query:
            def table(self, *_): return self
            def select(self, *_): return self
            def in_(self, *_): return self
            def eq(self, *_): return self
            def update(self, value): writes.append(value); return self
            def execute(self): return SimpleNamespace(data=[row])
        with patch('deep_dive.cover_question.generate_cover_question', return_value=cover_patch(self.result, self.research)):
            self.assertEqual(refresh_cover_questions(Query(), None, 'fixture', [7]), 1)
        self.assertEqual(set(writes[0]), {'analysis'})
        for key, value in original.items():
            self.assertEqual(writes[0]['analysis'][key], value)
        self.assertNotIn('cover_question', original)

    def test_editor_failure_leaves_existing_event_untouched(self):
        row = {'event_id': 7, 'analysis': {}, 'research': self.research}
        class Query:
            def table(self, *_): return self
            def select(self, *_): return self
            def in_(self, *_): return self
            def eq(self, *_): return self
            def execute(self): return SimpleNamespace(data=[row])
            def update(self, *_): raise AssertionError('Must not mutate on editorial failure')
        with patch('deep_dive.cover_question.generate_cover_question', side_effect=ValueError('unsupported')):
            self.assertEqual(refresh_cover_questions(Query(), None, 'fixture', [7]), 0)


if __name__ == '__main__':
    unittest.main()
