import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from deep_dive.models import BinaryQuestion, NumericSeries
from deep_dive.editorial_overrides import curate_known_event

class CuratedUskudarTests(unittest.TestCase):
    def test_verified_result_curates_chart_without_replacing_the_ballot(self):
        data = NumericSeries(name='Son tur',unit='oy',comparison_axis='Aday',ordered=False,part_of_whole=True,
            source_name='AA',source_url='https://www.aa.com.tr/tr/gundem/uskudar-belediye-baskan-vekilligine-ak-partili-dundar-ziya-gultekin-secildi-/4050704',methodology_note='Son tur',
            points=[{'label':'Dündar Ziya Gültekin','value':23,'group':'Cumhur İttifakı'}, {'label':'Sibel Tan Çetinkaya','value':19,'group':'CHP/Yeni Parti'}])
        research=SimpleNamespace(event_id=75,event_title='Üsküdar başkanvekili seçimi',numeric_series=[data])
        question = BinaryQuestion(
            id='q1', question_type='metric',
            question="Üsküdar'daki oy dengesi kalıcı bir yönetim değişimine işaret ediyor mu?",
            data_anchor='Son turda 23 ve 19 oy çıktı; tek oylama kalıcı desteği göstermeyebilir.',
            why_it_matters='Sonucun sonraki kararlara ne ölçüde yansıyacağını tartmak için.',
            choice_labels={'yes': 'Kalıcı değişim işareti', 'no': 'Bu oylamaya özgü', 'unsure': 'Henüz belirsiz'},
        )
        ballot = [question]
        original = question.model_dump()
        analysis=SimpleNamespace(charts=[],binary_questions=ballot)
        curate_known_event(research,analysis)
        self.assertEqual([p.value for p in analysis.charts[0].points],[23,19])
        self.assertIs(analysis.binary_questions, ballot)
        self.assertEqual(analysis.binary_questions[0].model_dump(), original)
        data.points[0].value=22
        blank=SimpleNamespace(charts=[],binary_questions=ballot)
        curate_known_event(research,blank)
        self.assertEqual(blank.charts,[])
        self.assertIs(blank.binary_questions, ballot)
        self.assertEqual(blank.binary_questions[0].model_dump(), original)

if __name__=='__main__': unittest.main()
