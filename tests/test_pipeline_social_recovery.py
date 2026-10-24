"""Research failures cannot skip social measurement of already publishable news."""
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import run_pipeline


class SocialRecoveryTests(unittest.TestCase):
    def exercise(self, failure):
        calls=[]
        ledger=Mock(return_value={'ok':True})
        def run(command, **kwargs):
            name=Path(command[1]).name
            calls.append((name,kwargs['env'].get('NOTRON_X_PHASE'),list(command)))
            if name==failure and '--validate-only' not in command:
                raise subprocess.CalledProcessError(1,command)
            return SimpleNamespace(returncode=0)
        with tempfile.TemporaryDirectory() as directory:
            backend=Path(directory)
            for name in run_pipeline.STEPS:(backend/name).touch()
            with patch.object(run_pipeline,'BACKEND',backend), \
                 patch.dict(os.environ,{'SUPABASE_URL':'test','SUPABASE_KEY':'test','OPENAI_API_KEY':'test'},clear=True), \
                 patch.dict(sys.modules,{'supabase':SimpleNamespace(create_client=Mock()),'daily_budget':SimpleNamespace(ledger=ledger)}), \
                 patch.object(sys,'argv',['run_pipeline.py','--mode','economy']), \
                 patch.object(run_pipeline.subprocess,'run',side_effect=run):
                result=run_pipeline.main()
        return result,calls,ledger

    def test_partial_research_still_measures_social_then_keeps_batch_incomplete(self):
        result,calls,ledger=self.exercise('generate_event_deep_dives.py')
        self.assertEqual(result,1)
        self.assertIn(('update_event_popularity_v02.py','measure'),[(name,phase) for name,phase,_ in calls])
        self.assertIn('--validate-only',calls[-1][2])
        outcome=ledger.call_args.kwargs['p_result']
        self.assertFalse(outcome['complete'])
        self.assertEqual(outcome['reason'],'research_incomplete_social_refresh_finished')
        self.assertEqual([c.args[1] for c in ledger.call_args_list],['begin','finish'])

    def test_fetch_failure_does_not_start_paid_social_or_claim_success(self):
        result,calls,ledger=self.exercise('rss_fetcher.py')
        self.assertEqual(result,1)
        self.assertEqual([name for name,_,_ in calls],['rss_fetcher.py'])
        self.assertFalse(ledger.call_args.kwargs['p_result']['complete'])

    def test_successful_research_preserves_normal_measurement_and_completion(self):
        result,calls,ledger=self.exercise(None)
        self.assertEqual(result,0)
        self.assertEqual(sum(name=='update_event_popularity_v02.py' and phase=='measure' for name,phase,_ in calls),1)
        self.assertTrue(ledger.call_args.kwargs['p_result']['complete'])
