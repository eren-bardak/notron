import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from deep_dive.background_context import apply_context, curated_uskudar, story_signature


class BackgroundContextTests(unittest.TestCase):
    def test_curated_story_separates_stay_and_party_response(self):
        context = curated_uskudar({'event': {'id': 75, 'title': 'Üsküdar seçim yenilendi'}})
        self.assertIn('beş oy', context.narration)
        self.assertIn('Belediye ise', context.narration)
        self.assertIn('esastan iptali değil', context.narration)
        self.assertTrue(context.evidence)
        self.assertIsNone(curated_uskudar({'event': {'id': 76, 'title': 'Üsküdar'}}))

    def test_background_write_preserves_question_chart_and_concurrent_guard(self):
        original = {'binary_questions': [{'id':'old', 'data_anchor':'42 oy'}], 'charts': [{'points':[23,19]}], 'editorial_review': {'revision':2}, 'card_summary':'Somut olay.', 'cover_question':'Hız mı, uzlaşma mı?', 'card_narration':{'url':'old-audio'}}
        row = {'event_id':75, 'analysis':deepcopy(original), 'research':{'evidence':[]}, 'generated_at':'2026-09-08T12:00:00Z'}
        writes, filters = [], []
        class DB:
            def table(self,*_): return self
            def update(self,value): writes.append(value); return self
            def eq(self,*args): filters.append(args); return self
            def execute(self): return SimpleNamespace(data=[row])
        context=curated_uskudar({'event':{'id':75,'title':'Üsküdar'}})
        apply_context(DB(),row,context,'signature')
        for key in original:
            if key != 'card_narration': self.assertEqual(writes[0]['analysis'][key],original[key])
        self.assertNotIn('card_narration',writes[0]['analysis'])
        self.assertIn(('generated_at',row['generated_at']),filters)
        self.assertEqual(row['analysis'],original)

    def test_new_coverage_invalidates_context_cache(self):
        payload={'event':{'id':75,'title':'Üsküdar','summary':'Seçim'},'articles':[{'id':1}]}
        self.assertNotEqual(story_signature(payload),story_signature({**payload,'articles':[{'id':1},{'id':2}]}))
        self.assertNotEqual(story_signature(payload),story_signature({**payload,'articles':[{'id':1,'description':'Düzeltilen haber'}]}))


if __name__ == '__main__':
    unittest.main()
