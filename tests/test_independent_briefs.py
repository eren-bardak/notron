import json
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import generate_event_briefs as briefs
from daily_budget import BudgetError


class IndependentBriefTests(unittest.TestCase):
    def test_bad_middle_story_does_not_prevent_later_story_save(self):
        saved = []
        payloads = {i: {'event_id': i} for i in (1, 2, 3)}
        def review(client, db, payload, now):
            if payload['event_id'] == 2:
                raise ValueError('bad structured response')
            saved.append(payload['event_id'])
            return 1
        with patch.object(briefs, 'review_one_brief', side_effect=review) as call:
            with self.assertRaisesRegex(RuntimeError, r'\[2\]'):
                briefs.review_independent_briefs(None, None, payloads, datetime.now(timezone.utc))
        self.assertEqual(saved, [1, 3])
        self.assertEqual(call.call_count, 3)

    def test_global_budget_failure_stops_further_paid_requests(self):
        with patch.object(briefs, 'review_one_brief', side_effect=[1, BudgetError('limit'), 1]) as call:
            with self.assertRaises(BudgetError):
                briefs.review_independent_briefs(None, None, {i: {'event_id': i} for i in (1, 2, 3)}, datetime.now(timezone.utc))
        self.assertEqual(call.call_count, 2)

    def test_each_request_contains_only_its_own_story_and_null_parse_is_a_failure(self):
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=None)
        payload = {'event_id': 42, 'articles': []}
        with self.assertRaisesRegex(ValueError, 'no parsed answer'):
            briefs.review_one_brief(client, None, payload, datetime.now(timezone.utc))
        request = client.responses.parse.call_args.kwargs
        self.assertEqual(json.loads(request['input'][1]['content'])['events'], [payload])
        self.assertLessEqual(request['max_output_tokens'], 3000)
