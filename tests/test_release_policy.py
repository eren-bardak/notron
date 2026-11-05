"""Regression checks for release gates and accidental paid push triggers."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_yaml(path):
    # BaseLoader keeps GitHub's `on` key a string (YAML 1.1 treats it as bool).
    return yaml.load((ROOT / path).read_text(), Loader=yaml.BaseLoader)


class ReleasePolicyTests(unittest.TestCase):
    def test_every_release_and_pr_runs_unconditional_offline_checks(self):
        workflow = read_yaml('.github/workflows/news-pipeline.yml')
        for event in ('push', 'pull_request', 'merge_group'):
            self.assertIn(event, workflow['on'])
            trigger = workflow['on'][event] or {}
            self.assertNotIn('paths', trigger)
            self.assertNotIn('paths-ignore', trigger)
        checks = workflow['jobs']['checks']
        self.assertNotIn('if', checks)
        self.assertNotIn('continue-on-error', checks)
        test = next(s for s in checks['steps'] if s.get('run') == 'python backend/run_pipeline.py --mode test')
        self.assertNotIn('if', test)
        self.assertNotIn('continue-on-error', test)
        for job in ('refresh', 'maintenance'):
            self.assertEqual(workflow['jobs'][job]['needs'], 'checks')
            self.assertIn("github.event_name == 'workflow_dispatch' &&", workflow['jobs'][job]['if'])
            self.assertNotIn('head_commit', workflow['jobs'][job]['if'])

    def test_only_existing_cron_schedules_news_with_build_gate(self):
        blueprint = read_yaml('render.yaml')
        self.assertEqual(len(blueprint['services']), 1)
        cron = blueprint['services'][0]
        self.assertEqual(cron['name'], 'notron-daily-news')
        self.assertEqual(cron['schedule'], '0 7 * * *')
        self.assertEqual(cron['autoDeployTrigger'], 'checksPass')
        self.assertIn('&& python backend/run_pipeline.py --mode test', cron['buildCommand'])
        self.assertEqual(cron['startCommand'], 'timeout --signal=TERM --kill-after=10s 20m python backend/run_pipeline.py --mode economy')
        for path in (ROOT / '.github/workflows').glob('*.yml'):
            self.assertNotIn('schedule', read_yaml(path)['on'])

    def test_legacy_paid_maintenance_is_manual_only(self):
        for path in ('background-context', 'card-stories'):
            workflow = read_yaml(f'.github/workflows/{path}.yml')
            self.assertEqual(set(workflow['on']), {'workflow_dispatch'})


if __name__ == '__main__':
    unittest.main()
