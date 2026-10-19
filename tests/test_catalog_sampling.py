import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog_sampling import sample_articles, category_batches
from event_catalog import category_id


class CatalogSamplingTests(unittest.TestCase):
    def test_category_group_can_find_same_occurrence_in_general_feed(self):
        rows=[{'id':1,'title':'Orionid meteor yağmuru bu gece','category_hint':'technology'},
              {'id':2,'title':'Meteor yağmuru Orionid için hazırlık','category_hint':'general'},
              {'id':3,'title':'Mecliste bütçe görüşmeleri','category_hint':'politics'}]
        groups=dict(category_batches(rows))
        self.assertEqual({r['id'] for r in groups['technology']},{1,2})
        self.assertEqual({r['id'] for r in groups['politics']},{3})

    def test_named_book_can_link_culture_and_political_reporting(self):
        rows=[{'id':1,'title':'Nutuk dünyaya açılıyor','category_hint':'entertainment'},
              {'id':2,'title':'Bakan Ersoy Nutuk için konuştu','category_hint':'politics'}]
        self.assertEqual(len(dict(category_batches(rows))['entertainment']),2)
    def test_prolific_publisher_does_not_displace_smaller_category(self):
        rows = [{'id': i, 'title': 'Gündem haberi', 'source': 'Large', 'url': f'https://a.test/gundem/{i}'} for i in range(100)]
        rows += [{'id': 101, 'title': 'Yeni keşif', 'source': 'Small', 'url': 'https://b.test/bilim-teknoloji/discovery'}]
        result = sample_articles(rows, 5)
        self.assertEqual(len(result), 5)
        self.assertIn(101, [row['id'] for row in result])

    def test_new_articles_lead_each_publisher_category(self):
        rows = [{'id': 2, 'title': 'Eski', 'source': 'Same', 'clustered_at': '2026-10-18'},
                {'id': 1, 'title': 'Yeni', 'source': 'Same', 'clustered_at': None}]
        self.assertEqual(sample_articles(rows, 1)[0]['id'], 1)

    def test_general_news_is_not_assigned_to_politics_by_default(self):
        self.assertEqual(category_id(None, 'Pendik’te dere taştı'), 'general')
        self.assertEqual(category_id(None, 'TBMM anayasa görüşmeleri'), 'politics')
        self.assertEqual(category_id('general', 'Bakan sel bölgesine gitti'), 'general')


if __name__ == '__main__':
    unittest.main()
