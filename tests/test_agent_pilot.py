import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from agent_pilot import evaluate


class AgentPilotTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 5, 13, tzinfo=timezone.utc)
        self.snapshot = {
            'observed_at': '2026-11-05T12:59:00Z',
            'agent_budget': {'month_utc': '2026-11', 'costs_complete': True,
                             'api_charged_cents': 1000, 'api_reserved_cents': 200,
                             'other_charged_cents': 100, 'other_reserved_cents': 1900,
                             'next_run_max_cents': 200},
            'news': {'status': 'completed', 'latest_published_at': '2026-11-05T07:20:00Z'},
        }

    def test_preview_never_authorizes_execution_or_news_retry(self):
        report = evaluate(self.snapshot, self.now)
        self.assertTrue(report['development_budget_candidate'])
        self.assertFalse(report['execution_authorized'])
        self.assertEqual(report['news_action'], 'observe_existing_render_cron_only')
        self.assertEqual(report['alerts'], [])

    def test_uncertain_reserved_money_is_not_available(self):
        self.snapshot['agent_budget']['api_reserved_cents'] = 7000
        report = evaluate(self.snapshot, self.now)
        self.assertFalse(report['development_budget_candidate'])
        self.assertIn('agent_budget_exhausted', report['alerts'])

    def test_total_costs_also_limit_admission(self):
        self.snapshot['agent_budget']['other_reserved_cents'] = 9000
        self.assertFalse(evaluate(self.snapshot, self.now)['development_budget_candidate'])

    def test_unknown_stale_future_wrong_month_and_malformed_costs_fail_closed(self):
        changes = [({'observed_at': '2026-11-05T12:00:00Z'}, {}),
                   ({'observed_at': '2026-11-05T14:00:00Z'}, {}),
                   ({}, {'month_utc': '2026-10'}), ({}, {'costs_complete': False}),
                   ({}, {'api_charged_cents': -1}), ({}, {'api_charged_cents': True}),
                   ({}, {'api_charged_cents': 1.5}), ({}, {'next_run_max_cents': 0})]
        for outer, inner in changes:
            with self.subTest(outer=outer, inner=inner):
                snapshot = copy.deepcopy(self.snapshot)
                snapshot.update(outer)
                snapshot['agent_budget'].update(inner)
                report = evaluate(snapshot, self.now)
                self.assertFalse(report['development_budget_candidate'])
                self.assertIn('unknown_or_stale_evidence', report['alerts'])

    def test_news_failure_and_staleness_are_visible(self):
        self.snapshot['news'].update(status='failed', latest_published_at='2026-11-03T07:20:00Z')
        report = evaluate(self.snapshot, self.now)
        self.assertIn('news_failed_no_automatic_retry', report['alerts'])
        self.assertIn('news_publication_stale_or_invalid', report['alerts'])

    def test_running_lease_cannot_hide_stuck_work(self):
        self.snapshot['news'].update(status='running', started_at='2026-11-05T12:00:00Z')
        self.assertIn('news_lease_or_runtime_needs_inspection', evaluate(self.snapshot, self.now)['alerts'])
