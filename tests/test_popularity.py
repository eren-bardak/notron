import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from popularity import score_event, normalize, question_ids, current_score, read_all
from pipeline_visibility import ready_event_ids

NOW = datetime(2026, 9, 8, 12, tzinfo=timezone.utc)
QUESTIONS = {'binary_questions': [{'question': 'Öncelik verilmeli mi?'}, {'question':'Denetlenmeli mi?'}, {'question':'Bu artış ne gösteriyor?', 'question_type':'metric', 'data_anchor':'2025: %12'}]}

def article(i, source, hours=0, **extra):
    return {'id': i, 'source': source, 'title': f'News {i}', 'url': f'https://example.org/{i}', 'published_at': (NOW-timedelta(hours=hours)).isoformat(), **extra}

def score(news, now=NOW, **extra):
    return score_event({'id':1}, [{'event_id':1,'news_id':n['id']} for n in news], {n['id']:n for n in news},
                       {normalize('A'):'left', normalize('B'):'right', normalize('C'):'center'},
                       extra.get('micro',[]),extra.get('comments',[]),extra.get('answers',[]), QUESTIONS,now)

class ScoreTests(unittest.TestCase):
    def test_same_snapshot_retries_do_not_inflate_and_six_hours_halves(self):
        news=[article(1,'A'),article(2,'B')]
        self.assertEqual(score(news)['score'],33)
        self.assertEqual(score(news)['score'],score(news)['score'])
        self.assertEqual(score(news, NOW+timedelta(hours=6))['score'],16.5)
        self.assertEqual(score(news, NOW+timedelta(hours=12))['score'],8.25)

    def test_new_activity_does_not_refresh_old_points(self):
        news=[article(1,'A',6),article(2,'B',6),article(3,'C')]
        self.assertEqual(score(news)['score'],24.5)  # previous 33 / 2, plus article 5 and new publisher 3

    def test_first_second_group_earns_bonus_once(self):
        self.assertEqual(score([article(1,'A'),article(2,'A')])['score'],10)
        self.assertEqual(score([article(1,'A'),article(2,'A'),article(3,'B')])['score'],38)
        self.assertEqual(score([article(1,'A'),article(2,'B'),article(3,'C')])['score'],41)
        self.assertEqual(score([article(1,'A'),article(2,'Unknown')])['score'],10)

    def test_duplicate_links_urls_and_titles_do_not_create_points_or_sources(self):
        original=article(1,'A')
        repeated=article(2,'B',url=original['url']+'?utm_campaign=copy')
        repeated_title=article(3,'A',title=original['title'])
        result=score([original,original,repeated,repeated_title])
        self.assertEqual(result['score'],5)
        self.assertEqual(result['source_count'],1)

    def test_bad_and_future_dates_never_earn_points(self):
        self.assertEqual(score([article(1,'A',-1),article(2,'B',published_at='bad')])['score'],0)

    def test_malformed_analysis_and_ballots_do_not_abort_scoring(self):
        for analysis in (None, [], {'binary_questions':1}, {'binary_questions':[{'question':None}, {'question':[]}, None]}):
            self.assertEqual(question_ids(analysis),set())
        qid=next(iter(question_ids(QUESTIONS)))
        invalid={'event_id':1,'user_id':'u1','created_at':NOW.isoformat(),'binary_answers':{qid:[]}}
        self.assertEqual(score([],answers=[invalid])['vote_count'],0)

    def test_real_unique_participation_only_and_edits_keep_original_age(self):
        base={'event_id':1,'created_at':(NOW-timedelta(hours=6)).isoformat(),'user_id':'u1','status':'active','text':'A thought'}
        micro=[dict(base,id=1),dict(base,id=2,created_at=NOW.isoformat()),dict(base,id=3,user_id='u2',status='hidden')]
        comments=[dict(base,id=1,author_role='writer'),dict(base,id=2,author_role='reader',user_id='u3'),
                  dict(base,id=3,author_role='writer',user_id=None)]
        qid=next(iter(question_ids(QUESTIONS)))
        answers=[dict(base,id=1,binary_answers={qid:'yes'},updated_at=NOW.isoformat()),dict(base,id=2,user_id='u2',binary_answers={'fake':'yes'})]
        result=score([],micro=micro,comments=comments,answers=answers)
        self.assertEqual(result['score'],2.5) # (micro1 + ballot1 + writer3) / 2
        self.assertEqual((result['micro_count'],result['vote_count'],result['writer_count']),(1,1,1))

    def test_snapshot_decay_matches_full_recomputation(self):
        news=[article(1,'A',3),article(2,'B',1)]
        event={'id':1,'popularity_score':score(news)['score'],'popularity_updated_at':NOW.isoformat()}
        later=NOW+timedelta(hours=4)
        self.assertAlmostEqual(current_score(event,later),score(news,later)['score'])

    def test_publisher_breadth_is_capped_and_repeat_coverage_cannot_refresh_it(self):
        rows = [article(i, chr(64+i), 6) for i in range(1, 8)]
        sides = {normalize(a['source']): None for a in rows}
        def calculate(news):
            return score_event({'id':1}, [{'event_id':1,'news_id':a['id']} for a in news],
                {a['id']:a for a in news}, sides, [], [], [], QUESTIONS, NOW)
        self.assertEqual(calculate(rows)['publisher_breadth_score'], 6)  # 12 / 2
        repeated = rows + [article(8, 'B'), article(9, 'Invented publisher')]
        self.assertEqual(calculate(repeated)['publisher_breadth_score'], 6)

    def test_reaction_labels_are_part_of_ballot_identity(self):
        q = {'question':'Bu gelişme sana ne hissettirdi?', 'choice_labels':{'yes':'Umut verdi','no':'Kaygı verdi','unsure':'Etkilemedi'}}
        original = question_ids({'binary_questions':[q]})
        self.assertTrue(next(iter(original)).startswith('n4_'))
        changed = {**q, 'choice_labels':{**q['choice_labels'],'yes':'Güven verdi'}}
        self.assertNotEqual(original, question_ids({'binary_questions':[changed]}))
        self.assertNotEqual(original, question_ids({'binary_questions':[{'question':q['question']}]}))
        self.assertEqual(original, question_ids({'binary_questions':[None, {}, q]}))

    def test_historical_group_crossing_does_not_refresh_after_old_article_expires(self):
        result=score([article(1,'A',37),article(2,'B',36),article(3,'A')])
        expected=5*2**(-37/6)+5*2**(-36/6)+5+23*2**(-36/6)
        self.assertAlmostEqual(result['score'],expected)

    def test_read_all_paginates_and_propagates_failure(self):
        class Query:
            def __init__(self): self.offsets=[]
            def table(self,*args): return self
            def select(self,*args): return self
            def order(self,*args): return self
            def range(self,a,b): self.offsets.append(a);return self
            def execute(self):
                size=1000 if self.offsets[-1]==0 else 1
                return type('Result',(),{'data':[{}]*size})()
        db=Query();self.assertEqual(len(read_all(db,'table','id')),1001);self.assertEqual(db.offsets,[0,1000])
        class Failed(Query):
            def execute(self): raise RuntimeError('Read failed')
        with self.assertRaisesRegex(RuntimeError,'Read failed'):
            read_all(Failed(),'table','id')

    def test_publication_requires_threshold_and_research_for_both_feeds(self):
        def event(i,**changes):
            return {'id':i,'created_at':NOW.isoformat(),'popularity_updated_at':NOW.isoformat(),'popularity_score':30-i,
                    'enough_data':True,'problem_supported':True,'source_count':2,
                    'numeric_data':[{'ordered':True,'source_url':'https://example.org/data','points':[{'label':'2024','value':1},{'label':'2025','value':2}]}],**changes}
        rows=[event(i) for i in range(1,6)]+[event(6,popularity_score=4.99),event(7,numeric_data=[])]
        analysis={**QUESTIONS,'editorial_review':{'revision':2,'question_intent':'event_implication','event_specific':True,'matches_displayed_evidence':True,'evidence_relevant':True,'not_factual_recall':True},'charts':[{'chart_type':'line','source_urls':['https://example.org/data'],'points':[{'label':'2024','value':1},{'label':'2025','value':2}]}]}
        analyses=[{'event_id':i,'status':'ready','analysis':analysis} for i in range(1,8)]
        ids=ready_event_ids(rows,analyses,NOW)
        self.assertEqual(ids[:3],[1,2,3]);self.assertEqual(ids[3:],[4,5])
        analyses[0]['analysis']={'binary_questions':[{}, {}, {}]}
        self.assertNotIn(1,ready_event_ids(rows,analyses,NOW))

if __name__=='__main__': unittest.main()
