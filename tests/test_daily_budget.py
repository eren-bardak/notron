import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from daily_budget import BudgetedResponses, BudgetError, coverage_rank, request_limits, usage_charge


class DailyBudgetTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.db = Mock()
        self.db.rpc.return_value.execute.return_value.data = {'ok': True}
        self.response = SimpleNamespace(usage=SimpleNamespace(input_tokens=1000, output_tokens=2000),
                                        output=[SimpleNamespace(type='web_search_call')])
        self.api.parse.return_value = self.response
        self.client = BudgetedResponses(self.api, self.db)
        self.env = patch.dict(os.environ, {'NOTRON_RUN_ID': 'test-run'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_unavailable_or_exhausted_ledger_makes_no_paid_call(self):
        for data in ({'ok': False, 'reason': 'daily budget would be exceeded'}, None):
            self.db.rpc.return_value.execute.return_value.data = data
            with self.assertRaises(BudgetError):
                self.client.parse(model='gpt-6-luna', input='news')
        self.api.parse.assert_not_called()

    def test_timeout_retains_reservation_and_stops_batch(self):
        self.api.parse.side_effect = TimeoutError()
        with self.assertRaisesRegex(BudgetError, 'reservation retained'):
            self.client.parse(model='gpt-6-luna', input='news', tools=[{'type':'web_search'}])
        operations = [c.args[1]['p_operation'] for c in self.db.rpc.call_args_list]
        self.assertEqual(operations, ['reserve'])

    def test_success_settles_usage_after_reserving(self):
        result = self.client.parse(model='gpt-6-luna', input='news', tools=[{'type':'web_search'}])
        self.assertIs(result, self.response)
        operations = [c.args[1] for c in self.db.rpc.call_args_list]
        self.assertEqual([c['p_operation'] for c in operations], ['reserve', 'settle'])
        self.assertEqual(operations[0]['p_request_id'], operations[1]['p_request_id'])
        self.assertEqual(operations[0]['p_amount'], 900000)
        self.assertEqual(operations[1]['p_amount'], 12926)
        options = self.api.parse.call_args.kwargs
        self.assertEqual(options['max_tool_calls'], 2)
        self.assertEqual(options['max_output_tokens'], 12000)
        self.assertEqual(options['service_tier'], 'default')

    def test_missing_usage_keeps_reservation(self):
        self.api.parse.return_value = SimpleNamespace(usage=None)
        with self.assertRaisesRegex(BudgetError, 'Missing API usage'):
            self.client.parse(model='gpt-6-luna', input='news')
        self.assertEqual(self.db.rpc.call_count, 1)

    def test_unpriced_requests_rejected_before_reservation(self):
        options = [
            {'model':'another-model'},
            {'model':'gpt-6-luna','tools':[{'type':'image_generation'}]},
            {'model':'gpt-6-luna','previous_response_id':'old-response'},
            {'model':'gpt-6-luna','input':'x'*180001},
            {'model':'gpt-6-luna','extra_body':{'service_tier':'priority'}},
            {'model':'gpt-6-luna','input':[{'role':'user','content':[{'type':'input_image','image_url':'https://example.org/image.png'}]}]},
        ]
        for option in options:
            with self.subTest(option=list(option)):
                with self.assertRaises(BudgetError):
                    self.client.parse(**option)
        self.db.rpc.assert_not_called()
        self.api.parse.assert_not_called()

    def test_output_limit_can_only_be_lowered(self):
        limited, amount = request_limits({'model':'gpt-6-luna','input':'news','max_output_tokens':20000})
        self.assertEqual(limited['max_output_tokens'], 12000)
        self.assertEqual(amount, 70000)

    def test_search_envelope_covers_all_three_full_context_passes(self):
        maximum = SimpleNamespace(usage=SimpleNamespace(input_tokens=3*1050000,output_tokens=12000),
                                  output=[SimpleNamespace(type='web_search_call')]*2)
        self.assertLessEqual(usage_charge(maximum), 900000)

    def test_integrated_popularity_orders_selection_then_publisher_breadth(self):
        stories = [{'id':1,'source_count':2,'article_count':20,'popularity_score':100},
                   {'id':2,'source_count':5,'article_count':8,'popularity_score':10},
                   {'id':3,'source_count':5,'article_count':9,'popularity_score':5}]
        self.assertEqual([e['id'] for e in sorted(stories, key=coverage_rank)], [1,2,3])


if __name__ == '__main__':
    unittest.main()
