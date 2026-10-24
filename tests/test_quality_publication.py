from country_scope_fixture import COUNTRY_DATA
import copy,sys,unittest
from pathlib import Path
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from editorial_quality import publication_quality
from generate_event_briefs import select_pending, BriefDraft, materialize_brief, validate_brief
from test_analysis_evidence import draft_data, SOURCE_A, SOURCE_B, NOW
from popularity import score_event,normalize,question_ids

class QualityTests(unittest.TestCase):
    def test_source_excerpt_fallback_preserves_originals_and_evidence_identity(self):
        from generate_event_briefs import enrich_excerpts
        row={'id':1,'url':SOURCE_A,'source':'Original','description':'Short RSS excerpt'}
        rich=enrich_excerpts([row],lambda url:'Publisher article context. '*80)
        self.assertEqual(row['description'],'Short RSS excerpt')
        self.assertEqual(rich[0]['id'],row['id'])
        self.assertEqual(rich[0]['url'],SOURCE_A)
        self.assertGreater(len(rich[0]['description']),900)
        self.assertEqual(enrich_excerpts([row],lambda url:''),[row])

    def test_brief_copies_original_evidence_without_model_retyping(self):
        payload={'event_id':213,'articles':[{'id':i,'source':source,'title':'Kaynak haberi','description':'Kaynağın yayımladığı özgün açıklama.','url':url,'published_at':NOW.isoformat()}
            for i,source,url in [(1,'Birinci',SOURCE_A),(2,'İkinci',SOURCE_B)]]}
        analysis=draft_data(numeric=False)
        analysis['editorial_review']={'revision':2,'question_intent':'event_implication','event_specific':True,
            'matches_displayed_evidence':True,'evidence_relevant':True,'not_factual_recall':True,
            'tradeoff_present':True,'balanced_choices':True,'non_normative':True,'substantive_disagreement':True,'reason':'Kaynaklar belirsizlikleri açıklıyor.'}
        draft=BriefDraft.model_validate({'event_id':213,'evidence_article_ids':[1,2],'analysis':analysis})
        brief=materialize_brief(draft,payload)
        self.assertTrue(validate_brief(brief,payload))
        self.assertEqual(brief.evidence[0].finding,payload['articles'][0]['description'])
        self.assertEqual(brief.evidence[0].published_at,payload['articles'][0]['published_at'])
        missing=copy.deepcopy(analysis);missing['publication_review']=None
        with self.assertRaises(ValueError):
            BriefDraft.model_validate({'event_id':213,'evidence_article_ids':[1,2],'analysis':missing})
        draft.evidence_article_ids=[1,999]
        with self.assertRaises(ValueError):materialize_brief(draft,payload)

    def test_thin_repeated_context_and_low_news_value_never_publish(self):
        good={'publication_review':{'revision':1,'newsworthy':True,'basis':'public_impact','reason':'Kamu hizmetlerini etkileyen yeni uygulama somut olarak açıklanmış.'},
              'background':{'narration':'Önceki kararın uygulaması farklı kurumları ve katılımcıları etkiledi. Yeni görüşmeler bu uygulamada karşılaşılan belirsizlikleri ele alıyor. Kaynaklar önceki aşamayı yeni sonuçtan ayrı açıklıyor.'},
              'event_explanation':{'narration':'Kurum yeni kararını açıkladı ve uygulamanın bir sonraki aşamasına ilişkin bilgileri paylaştı. Sonuçların etkisi ilerleyen açıklamalarla izlenebilecek.'}}
        self.assertTrue(publication_quality(good))
        for mutate in (lambda x:x['publication_review'].update(newsworthy=False),
                       lambda x:x['background'].update(narration='  '),
                       lambda x:x.update(background=x['event_explanation'])):
            bad=copy.deepcopy(good);mutate(bad);self.assertFalse(publication_quality(bad))
        good['background']['narration']='Önceki karar mahkemece iptal edilmişti.'
        good['event_explanation']['narration']='Kurum yeni kararını açıkladı.'
        self.assertTrue(publication_quality(good))

    def test_cheap_pass_never_rewrites_a_saved_ballot(self):
        now=datetime.now(timezone.utc)
        rows=[{'id':i,'data':COUNTRY_DATA,'popularity_score':20,'popularity_updated_at':now.isoformat(),'left_source_count':1,'right_source_count':1,'source_count':2} for i in (1,2)]
        stored=[{'event_id':1,'status':'insufficient_data','analysis':{'binary_questions':[{'question':'Önceki soru?'}]}}]
        self.assertEqual([e['id'] for e in select_pending(rows,stored,now)],[2])

    def test_a_content_factory_cannot_outweigh_independent_publishers(self):
        now=datetime.now(timezone.utc)
        def points(sources):
            news={i:{'id':i,'source':source,'title':f'Title{i}','url':f'https://{source}.example/{i}','published_at':now.isoformat()} for i,source in enumerate(sources)}
            return score_event({'id':1},[{'event_id':1,'news_id':i} for i in news],news,{'a':'left','b':'right'},[],[],[],{},now)['score']
        self.assertEqual(points(['a']*100),7)
        self.assertEqual(points(['a','b']),16)
        self.assertGreater(points(['a','b']),points(['a']*100))
        # Center + left is not the required cross-spectrum pair.
        self.assertEqual(points(['a','c']),8)

    def test_community_contributions_are_unique_bounded_and_keep_their_age(self):
        now=datetime.now(timezone.utc)
        q={'binary_questions':[{'question':'Değişim neye işaret ediyor?'}]};qid=next(iter(question_ids(q)))
        votes=[{'event_id':1,'user_id':str(i),'created_at':now.isoformat(),'binary_answers':{qid:'yes'}} for i in range(1000)]
        comments=[{'event_id':1,'user_id':str(i),'created_at':now.isoformat(),'status':'active','text':'Somut bir yorum'} for i in range(1000)]
        value=score_event({'id':1},[],{},{},comments,[],votes,q,now)['score']
        self.assertEqual(value,15)
