import base64
import copy
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cloud_agents as a


class CloudAgentTests(unittest.TestCase):
    def test_tls_accepts_explicit_secure_uri(self):
        for scheme in ('postgres','postgresql'):
            for mode in ('require','verify-full'):
                dsn=f'{scheme}://test:fake%40password@db.example.invalid/db?sslmode={mode}'
                self.assertEqual(a.validate_database_tls(dsn),dsn)

    def test_tls_rejects_duplicate_ambiguous_or_insecure_configuration(self):
        prefix='postgresql://test:fake-password@db.example.invalid/db?'
        queries=('sslmode=require&sslmode=disable','sslmode=disable&sslmode=require',
                 'sslmode=require&sslmode=require','sslmode=require&%73slmode=disable',
                 'application_name=sslmode%3Drequire&sslmode=disable',
                 'sslmode=disable','sslmode=prefer','sslmode=',
                 'sslmode=require&service=other','sslmode=require&host=%2Ftmp',
                 'sslmode=require&dbname=other','sslmode=require&hostaddr=127.0.0.1',
                 'sslmode=require&application_name=a&application_name=b')
        invalid=[prefix+q for q in queries]+[
            prefix.rstrip('?'), 'host=example sslmode=require sslmode=disable',
            'postgresql://%2Ftmp/db?sslmode=require',
            'postgresql:///db?sslmode=require', prefix+'sslmode=require#fragment']
        for dsn in invalid:
            with self.subTest(dsn=dsn):
                with self.assertRaises(a.Stopped) as error:
                    a.validate_database_tls(dsn)
                self.assertNotIn('fake-password',str(error.exception))

    def test_tls_failure_stops_before_connecting_or_calling_providers(self):
        with patch.dict(os.environ,{'NOTRON_AGENTS_ENABLED':'true','GITHUB_RUN_ID':'123',
             'AGENT_DATABASE_URL':'postgresql://host/db?sslmode=require&sslmode=disable'}), \
             patch.object(sys,'argv',['cloud_agents','development']), \
             patch.object(a,'Ledger') as ledger, patch.object(a,'HTTP') as http:
            self.assertEqual(a.main(),1)
        ledger.assert_not_called()
        http.assert_not_called()

    def setUp(self):
        self.api = Mock()
        self.ledger = Mock()
        self.ledger.call.return_value = True
        self.response = {'status':'completed','usage':{'input_tokens':1000,'output_tokens':100},
                         'output':[{'type':'message','content':[{'type':'output_text','text':'answer'}]}]}
        self.api.request.return_value = self.response

    def test_reservation_precedes_api_and_settlement(self):
        timeline = Mock()
        timeline.attach_mock(self.ledger, 'ledger')
        timeline.attach_mock(self.api, 'api')
        self.assertEqual(a.ask(self.api,self.ledger,'run','prompt'),'answer')
        self.assertEqual([c[0] for c in timeline.mock_calls], ['ledger.call','api.request','ledger.call'])
        body = self.api.request.call_args.args[2]
        self.assertNotIn('tools',body)
        self.assertNotIn('previous_response_id',body)
        self.assertEqual(body['max_output_tokens'],6000)
        self.assertEqual(body['service_tier'],'default')

    def test_reservation_denial_never_calls_model(self):
        self.ledger.call.return_value=False
        with self.assertRaises(a.Stopped):
            a.ask(self.api,self.ledger,'run','prompt')
        self.api.request.assert_not_called()

    def test_timeout_unknown_usage_keeps_reservation(self):
        for failure in ('timeout','usage'):
            with self.subTest(failure=failure):
                self.ledger.reset_mock()
                self.api.request.side_effect = TimeoutError() if failure=='timeout' else None
                self.api.request.return_value = {'status':'completed','usage':None}
                with self.assertRaises((TimeoutError,a.Stopped)):
                    a.ask(self.api,self.ledger,'run','prompt')
                self.assertEqual([c.args[0] for c in self.ledger.call.call_args_list],['reserve'])

    def test_price_envelope_covers_worst_case(self):
        self.assertLess(a.charge({'input_tokens':200000,'output_tokens':6000}),1000000)
        for usage in ({}, {'input_tokens':True,'output_tokens':1}, {'input_tokens':200001,'output_tokens':1},
                      {'input_tokens':1,'output_tokens':6001}):
            with self.assertRaises(a.Stopped):
                a.charge(usage)

    def test_input_limit_before_any_spending(self):
        with self.assertRaises(a.Stopped):
            a.ask(self.api,self.ledger,'run','ç'*100001)
        self.ledger.call.assert_not_called()

    def test_proposal_cannot_edit_protected_paths_or_execute_code(self):
        for path in ('../x','backend/daily_budget.py','.github/workflows/news-pipeline.yml','agents/cloud_agents.py'):
            with self.assertRaises(ValueError):
                a.validate_proposal(json.dumps({'summary':'x','files':[{'path':path,'content':'x=1'}]}))
        with patch('builtins.print') as executed:
            a.validate_proposal(json.dumps({'summary':'x','files':[{'path':'backend/catalog_sampling.py','content':'print("NOT EXECUTED")'}]}))
        executed.assert_not_called()

    def test_only_constant_changes_are_eligible_for_automatic_release(self):
        before = "COMMON = {'haber', 'son'}\ndef f():\n return 1\n"
        after = "COMMON = {'haber', 'yeni'}\ndef f():\n return 1\n"
        self.assertTrue(a.safe_automatic_change(before,after))
        for invalid in (after.replace('return 1','return 2'), after+'\nimport os\n',
                        after.replace("'yeni'","open('/tmp/file')"), before,
                        "COMMON = {'haber'}\nCOMMON = {'son'}\ndef f():\n return 1\n"):
            self.assertFalse(a.safe_automatic_change(before,invalid))

    def test_disabled_controller_does_not_create_clients(self):
        with patch.dict(os.environ,{},clear=True), patch.object(sys,'argv',['cloud_agents','development']), \
             patch.object(a,'HTTP') as http, patch.object(a,'Ledger') as ledger:
            self.assertEqual(a.main(),0)
        http.assert_not_called()
        ledger.assert_not_called()

    def test_monitor_has_no_llm_or_github_dependency(self):
        snapshot={'observed_at':'2026-11-05T13:00:00Z','unsettled_calls':1,'news':{
            'started_at':'2026-11-05T07:00:00Z','finished_at':'2026-11-05T07:20:00Z',
            'result':{'complete':False},'latest_visible_created_at':'2026-11-03T10:00:00Z'}}
        self.ledger.call.side_effect=[snapshot,1]
        result=a.monitoring(self.ledger,datetime(2026,11,5,13,tzinfo=timezone.utc))
        self.assertEqual({x['code'] for x in result['findings']},
                         {'news_run_incomplete','visible_news_stale','agent_billing_uncertain'})
        self.assertEqual(self.ledger.call.call_args_list[1].args[0],'record_incidents')

    def test_stale_or_missing_monitor_evidence_is_failure(self):
        for snapshot in ({}, {'observed_at':'2020-01-01T00:00:00Z'}):
            self.assertIn({'code':'monitor_evidence_unavailable'}, a.monitor_findings(snapshot,datetime.now(timezone.utc)))

    def fake_github(self, checks=None, number=28, before=None, after=None):
        before = before or "COMMON = {'haber', 'son'}\n"
        after = after or "COMMON = {'haber', 'yeni'}\n"
        pr={'number':number,'user':{'login':'notron-dev[bot]'},'head':{'ref':'agents/abcd','sha':'head','repo':{'full_name':a.REPO}},
            'base':{'ref':'main'},'draft':False,'changed_files':1}
        checked=checks or [{'name':name,'status':'completed','conclusion':'success','app':{'slug':'github-actions'}} for name in a.REQUIRED_CHECKS]
        def request(method,path,body=None):
            suffix=path.split(a.REPO)[-1]
            if suffix=='': return {'private':False,'default_branch':'main','archived':False}
            if suffix=='/branches/main/protection': return {'enforce_admins':{'enabled':True},'required_status_checks':{'strict':True,'contexts':sorted(a.REQUIRED_CHECKS)},'required_pull_request_reviews':{'bypass_pull_request_allowances':{}}}
            if suffix.startswith('/pulls?'): return [pr]
            if suffix==f'/pulls/{number}': return pr
            if suffix=='/git/ref/heads/main': return {'object':{'sha':'base'}}
            if suffix=='/git/commits/head': return {'parents':[{'sha':'base'}]}
            if suffix.endswith('/files?per_page=100'): return [{'filename':'backend/catalog_sampling.py','status':'modified'}]
            if suffix.startswith('/contents/'):
                content=before if suffix.endswith('ref=base') else after
                return {'type':'file','encoding':'base64','size':len(content),'content':base64.b64encode(content.encode()).decode()}
            if suffix.startswith('/commits/'): return {'total_count':len(checked),'check_runs':checked}
            if suffix.endswith('/merge'): return {'merged':True}
            raise AssertionError((method,path))
        gh=Mock()
        gh.request.side_effect=request
        return gh

    def test_release_checks_exact_sha_and_never_touches_pr_27(self):
        gh=self.fake_github()
        self.assertEqual(a.release(gh,'notron-dev[bot]',self.ledger,'123:release')['status'],'merged')
        self.assertEqual(gh.request.call_args.args[2]['sha'],'head')
        blocked=self.fake_github(number=27)
        self.assertEqual(a.release(blocked,'notron-dev[bot]',self.ledger,'123:release')['status'],'no_eligible_pr')
        self.assertFalse(any(c.args[0]=='PUT' for c in blocked.request.call_args_list))

    def test_failed_skipped_tests_and_executable_changes_never_merge(self):
        for conclusion in ('failure','skipped','neutral',None):
            gh=self.fake_github(checks=[{'name':a.CHECK,'status':'completed','conclusion':conclusion,'app':{'slug':'github-actions'}}])
            self.assertEqual(a.release(gh,'notron-dev[bot]',self.ledger,'123:release')['status'],'no_eligible_pr')
        gh=self.fake_github(after="COMMON={'yeni'}\nprint('surprise')\n")
        self.assertEqual(a.release(gh,'notron-dev[bot]',self.ledger,'123:release')['status'],'no_eligible_pr')

    def test_developer_skips_open_agent_pr_without_spending(self):
        gh=self.fake_github()
        self.assertEqual(a.development(gh,self.api,self.ledger,'123:development')['status'],'skipped')
        self.api.request.assert_not_called()

    def test_release_requires_monthly_budget_claim_before_merge(self):
        gh=self.fake_github()
        self.ledger.call.return_value=False
        with self.assertRaises(a.Stopped):
            a.release(gh,'notron-dev[bot]',self.ledger,'123:release')
        self.assertFalse(any(c.args[0]=='PUT' for c in gh.request.call_args_list))

    def test_idle_release_does_not_consume_daily_merge_quota(self):
        gh=self.fake_github(after="COMMON={'yeni'}\nprint('surprise')\n")
        a.release(gh,'notron-dev[bot]',self.ledger,'123:release')
        self.ledger.call.assert_not_called()

    def test_full_development_cycle_creates_pr_without_executing_model_code(self):
        source="COMMON = {'haber'}\n"
        proposal={'summary':'Improve source sampling','files':[{'path':'backend/catalog_sampling.py','content':"COMMON = {'haber', 'yeni'}\n"}]}
        self.response['output'][0]['content'][0]['text']=json.dumps(proposal)
        def request(method,path,body=None):
            suffix=path.split(a.REPO)[-1]
            if suffix=='': return {'private':False,'default_branch':'main'}
            if suffix.startswith('/pulls?'): return []
            if suffix.startswith('/issues?'): return [{'number':3,'title':'Sampling fix','body':'Approved'}]
            if suffix=='/git/ref/heads/main': return {'object':{'sha':'base'}}
            if suffix=='/git/commits/base': return {'tree':{'sha':'tree'}}
            if suffix.startswith('/contents/'): return {'type':'file','encoding':'base64','size':len(source),'content':base64.b64encode(source.encode()).decode()}
            if suffix=='/git/trees': return {'sha':'new-tree'}
            if suffix=='/git/commits': return {'sha':'new-commit'}
            if suffix=='/git/refs': return {}
            if suffix=='/pulls': return {'number':31}
            raise AssertionError((method,path))
        gh=Mock()
        gh.request.side_effect=request
        result=a.development(gh,self.api,self.ledger,'123:development')
        self.assertEqual(result,{'status':'pr_created','pr':31,'sha':'new-commit','base':'base'})
        self.assertEqual(self.api.request.call_count,1)
        self.assertFalse(any(c.args[0]=='PUT' for c in gh.request.call_args_list))


if __name__=='__main__':
    unittest.main()
