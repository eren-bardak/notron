import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from deep_dive.models import NumericSeries
from deep_dive.editorial_overrides import curate_known_event

class CuratedUskudarTests(unittest.TestCase):
    def test_only_verified_exact_result_gets_the_editorial_question(self):
        data = NumericSeries(name='Son tur',unit='oy',comparison_axis='Aday',ordered=False,part_of_whole=True,
            source_name='AA',source_url='https://www.aa.com.tr/tr/gundem/uskudar-belediye-baskan-vekilligine-ak-partili-dundar-ziya-gultekin-secildi-/4050704',methodology_note='Son tur',
            points=[{'label':'Dündar Ziya Gültekin','value':23,'group':'Cumhur İttifakı'}, {'label':'Sibel Tan Çetinkaya','value':19,'group':'CHP/Yeni Parti'}])
        research=SimpleNamespace(event_id=75,event_title='Üsküdar başkanvekili seçimi',numeric_series=[data])
        analysis=SimpleNamespace(charts=[],binary_questions=[])
        curate_known_event(research,analysis)
        self.assertEqual([p.value for p in analysis.charts[0].points],[23,19])
        self.assertIn('hızlı karar',analysis.binary_questions[0].question)
        self.assertIn('geniş uzlaşma',analysis.binary_questions[0].question)
        self.assertEqual(analysis.binary_questions[0].choice_labels.unsure,'Karara göre değişir')
        data.points[0].value=22
        blank=SimpleNamespace(charts=[],binary_questions=[])
        curate_known_event(research,blank)
        self.assertEqual(blank.charts,[])

if __name__=='__main__': unittest.main()
