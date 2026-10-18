import os
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import Mock
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import run_pipeline
import clustering_news_enriched as clustering
import generate_event_deep_dives as research_pipeline


class PipelineModeTests(unittest.TestCase):
    def test_offline_mode_needs_no_credentials_and_removes_live_secrets(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "never-forward", "SUPABASE_KEY": "never-forward"}), \
             patch.object(sys, "argv", ["run_pipeline.py", "--mode", "test"]), \
             patch.object(run_pipeline.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertEqual(run_pipeline.main(), 0)
        command = run.call_args.args[0]
        self.assertTrue(command[1].endswith("offline_tests.py"))
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertNotIn("SUPABASE_KEY", run.call_args.kwargs["env"])

    def test_offline_failure_is_not_reported_as_success(self):
        with patch.object(sys, "argv", ["run_pipeline.py", "--mode", "test"]), \
             patch.object(run_pipeline.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(run_pipeline.main(), 1)

    def test_completed_day_does_not_start_any_pipeline_step(self):
        with patch.dict(os.environ, {'SUPABASE_URL':'test','SUPABASE_KEY':'test','OPENAI_API_KEY':'test'}), \
             patch.object(sys, 'argv', ['run_pipeline.py','--mode','economy']), \
             patch('supabase.create_client'), \
             patch('daily_budget.ledger', return_value={'ok':True,'skip':True}), \
             patch.object(run_pipeline.subprocess, 'run') as run:
            self.assertEqual(run_pipeline.main(), 0)
        run.assert_not_called()

    def test_economy_caps_override_larger_existing_settings(self):
        with patch.dict(os.environ, {"MAX_DEEP_DIVES_PER_RUN": "20", "MAX_CLUSTER_EVENTS": "20"}):
            env = run_pipeline.pipeline_environment("economy")
        self.assertEqual(env["MAX_DEEP_DIVES_PER_RUN"], "3")
        self.assertEqual(env["MAX_CLUSTER_EVENTS"], "18")
        self.assertEqual(env["MAX_CLUSTER_ARTICLES"], "300")
        self.assertEqual(env["NOTRON_PIPELINE_MODE"], "economy")
        self.assertEqual(env["OPENAI_EVENT_MODEL"], "gpt-6-luna")
        self.assertEqual(env["OPENAI_DEEP_DIVE_MODEL"], "gpt-6-luna")

    def test_full_mode_keeps_explicit_configuration(self):
        with patch.dict(os.environ, {"MAX_DEEP_DIVES_PER_RUN": "7", "NOTRON_PIPELINE_MODE": "economy",
                                     "OPENAI_EVENT_MODEL": "configured-model", "OPENAI_DEEP_DIVE_MODEL": "configured-research-model"}):
            env = run_pipeline.pipeline_environment("full")
        self.assertEqual(env["MAX_DEEP_DIVES_PER_RUN"], "7")
        self.assertEqual(env["NOTRON_PIPELINE_MODE"], "full")
        self.assertEqual(env["OPENAI_EVENT_MODEL"], "configured-model")
        self.assertEqual(env["OPENAI_DEEP_DIVE_MODEL"], "configured-research-model")

    def test_economy_model_override_applies_to_both_stages(self):
        with patch.dict(os.environ, {"OPENAI_ECONOMY_MODEL": "chosen-cheap-model"}):
            env = run_pipeline.pipeline_environment("economy")
        self.assertEqual(env["OPENAI_EVENT_MODEL"], "chosen-cheap-model")
        self.assertEqual(env["OPENAI_DEEP_DIVE_MODEL"], "chosen-cheap-model")

    def test_economy_grouping_limits_articles_and_does_not_search_or_enrich(self):
        now = datetime.now(timezone.utc).isoformat()
        articles = [{"id": i, "title": f"Story {i}", "source": f"Source {i % 2}",
                     "clustered_at": None, "published_at": now} for i in range(120)]
        db = Mock()
        def table(name):
            query = Mock()
            for method in ("select", "is_", "gte", "lte", "order", "limit", "in_"):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(data=articles if name == "news" else [])
            return query
        db.table.side_effect = table
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(output_parsed=SimpleNamespace(events=[]))
        with patch.dict(os.environ, {"SUPABASE_URL": "test", "SUPABASE_KEY": "test", "OPENAI_API_KEY": "test"}), \
             patch.object(clustering, "ECONOMY_MODE", True), \
             patch.object(clustering, "ARTICLE_LIMIT", 80), \
             patch.object(clustering, "create_client", return_value=db), \
             patch.object(clustering, "load_source_leanings", return_value={}), \
             patch.object(clustering, "OpenAI", return_value=client) as factory, \
             patch.object(clustering, "budget_client", side_effect=lambda client, db: client), \
             patch.object(clustering, "enrich_saved_events") as enrich:
            clustering.main()
        request = client.responses.parse.call_args.kwargs
        self.assertEqual(len(json.loads(request["input"][1]["content"])), 80)
        self.assertNotIn("tools", request)
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
        enrich.assert_not_called()

    def test_economy_does_not_report_an_incomplete_batch_as_success(self):
        now = datetime.now(timezone.utc).isoformat()
        events = [{"id": i, "created_at": now, "source_count": 2, "left_source_count": 1, "right_source_count": 1,
                   "popularity_score": 100, "popularity_updated_at": now} for i in (1, 2)]
        db = Mock()
        def table(name):
            query = Mock()
            for method in ("select", "gte", "lte", "order", "in_", "limit"):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(data=events if name == "events" else [])
            return query
        db.table.side_effect = table
        bundle = Mock(event_id=1, numeric_series=[], metric_candidates=[])
        analysis = SimpleNamespace(event_id=1, charts=[])
        with patch.dict(os.environ, {"SUPABASE_URL": "test", "SUPABASE_KEY": "test", "OPENAI_API_KEY": "test"}), \
             patch.object(sys, "argv", ["generate_event_deep_dives.py"]), \
             patch.object(research_pipeline, "ECONOMY_MODE", True), \
             patch.object(research_pipeline, "MAX_EVENTS_PER_RUN", 1), \
             patch.object(research_pipeline, "create_client", return_value=db), \
             patch.object(research_pipeline, "OpenAI"), \
             patch.object(research_pipeline, "budget_client", side_effect=lambda client, db: client), \
             patch.object(research_pipeline, "ledger", return_value={"event_ids": [1, 2]}), \
             patch.object(research_pipeline, "enforce_previous_year_gate", return_value=[]), \
             patch.object(research_pipeline, "load_event", return_value={}), \
             patch.object(research_pipeline, "research_event", return_value=bundle) as research, \
             patch.object(research_pipeline, "has_event_evidence", return_value=True), \
             patch.object(research_pipeline, "analyze_event", return_value=analysis) as analyze, \
             patch.object(research_pipeline, "save_analysis") as save, \
             patch.object(research_pipeline, "refresh_cover_questions") as covers, \
             patch.object(research_pipeline, "refresh_event_covers") as photos, \
             patch.object(research_pipeline, "refresh_background_contexts") as backgrounds, \
             patch.object(research_pipeline, "publish_ready_events", return_value=[1]) as publish:
            with self.assertRaisesRegex(RuntimeError, '1/2 cross-spectrum stories'):
                research_pipeline.main()
        self.assertEqual(research.call_count, 1)
        self.assertEqual(analyze.call_count, 1)
        self.assertEqual(save.call_count, 1)
        publish.assert_called_once_with(db)
        covers.assert_not_called()
        photos.assert_not_called()
        backgrounds.assert_not_called()

    def test_economy_researches_three_broadest_stories_and_verifies_publication(self):
        now = datetime.now(timezone.utc).isoformat()
        events = [{'id':i,'created_at':now,'source_count':i+1,'left_source_count':1,'right_source_count':1,'article_count':i*3,
                   'popularity_score':100,'popularity_updated_at':now} for i in (1,2,3,4)]
        db = Mock()
        def table(name):
            query = Mock()
            for method in ('select','gte','lte','order','in_','limit'):
                getattr(query, method).return_value = query
            query.execute.return_value = SimpleNamespace(data=events if name=='events' else [])
            return query
        db.table.side_effect = table
        with patch.dict(os.environ, {'SUPABASE_URL':'test','SUPABASE_KEY':'test','OPENAI_API_KEY':'test'}), \
             patch.object(sys,'argv',['generate_event_deep_dives.py']), \
             patch.object(research_pipeline,'ECONOMY_MODE',True), \
             patch.object(research_pipeline,'MAX_EVENTS_PER_RUN',3), \
             patch.object(research_pipeline,'create_client',return_value=db), \
             patch.object(research_pipeline,'OpenAI'), \
             patch.object(research_pipeline,'budget_client',side_effect=lambda client, db: client), \
             patch.object(research_pipeline,'ledger',return_value={'event_ids':[4,3,2]}) as select, \
             patch.object(research_pipeline,'enforce_previous_year_gate',return_value=[]), \
             patch.object(research_pipeline,'load_event',return_value={}), \
             patch.object(research_pipeline,'research_event',side_effect=lambda client, model, event_id, payload: Mock(event_id=event_id,numeric_series=[],metric_candidates=[])) as research, \
             patch.object(research_pipeline,'has_event_evidence',return_value=True), \
             patch.object(research_pipeline,'analyze_event',side_effect=lambda client, model, bundle: SimpleNamespace(event_id=bundle.event_id,charts=[])), \
             patch.object(research_pipeline,'save_analysis') as save, \
             patch.object(research_pipeline,'publish_ready_events',return_value=[2,3,4]):
            research_pipeline.main()
        self.assertEqual(select.call_args.kwargs['p_event_ids'], [4,3,2])
        self.assertEqual([call.args[2] for call in research.call_args_list], [4,3,2])
        self.assertEqual(save.call_count, 3)
