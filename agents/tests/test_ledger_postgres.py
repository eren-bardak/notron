"""Real transactional tests; LOCAL disposable Postgres only, never a hosted DB."""
import concurrent.futures
import json
import os
import sys
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cloud_agents import Ledger

DSN=os.getenv('AGENT_TEST_DATABASE_URL')


@unittest.skipUnless(DSN,'set AGENT_TEST_DATABASE_URL to a local disposable database')
class PostgresLedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config=conninfo_to_dict(DSN)
        if config.get('host') not in ('127.0.0.1','localhost') or config.get('dbname')!='notron_agents_test':
            raise RuntimeError('Refusing non-local or non-test database')
        cls.admin=psycopg.connect(DSN,autocommit=True)
        cls.admin.execute((Path(__file__).resolve().parents[1]/'schema.sql').read_text())
        cls.admin.execute('''create table if not exists public.notron_batch_runs(
            id uuid, started_at timestamptz, finished_at timestamptz, result jsonb);
            create table if not exists public.events(created_at timestamptz,is_visible boolean);
            revoke all on public.notron_batch_runs, public.events from public''')

    @classmethod
    def tearDownClass(cls):
        cls.admin.close()

    def setUp(self):
        self.admin.execute('truncate notron_agents.calls,notron_agents.runs,notron_agents.months,notron_agents.incidents')
        self.admin.execute("update notron_agents.control set enabled=true,price_valid_until=now()+interval '1 day'")
        self.admin.execute("insert into notron_agents.months(month,approved,other_reserve) values(date_trunc('month',now() at time zone 'UTC'),true,20000000)")
        self.ledger=Ledger(DSN)
        self.ledger.db.execute('set role notron_agent_dev')
        self.addCleanup(self.ledger.close)

    def begin(self):
        self.assertTrue(self.ledger.call('claim','run','development'))

    def test_duplicate_claim_and_reservation_do_not_authorize_more_calls(self):
        self.begin()
        self.assertFalse(self.ledger.call('claim','run','development'))
        self.assertFalse(self.ledger.call('claim','different','development'))
        call=str(uuid.uuid4())
        self.assertTrue(self.ledger.call('reserve','run',call))
        self.assertTrue(self.ledger.call('settle','run',call,100))
        self.assertFalse(self.ledger.call('reserve','run',call))

    def test_two_concurrent_claims_have_one_winner(self):
        def claim(n):
            with psycopg.connect(DSN,autocommit=True) as db:
                db.execute('set role notron_agent_dev')
                return db.execute("select notron_agents.claim(%s,'development')",(str(n),)).fetchone()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(claim,range(8))),1)

    def test_concurrent_reservations_cannot_double_spend(self):
        self.begin()
        def reserve(n):
            with psycopg.connect(DSN,autocommit=True) as db:
                db.execute('set role notron_agent_dev')
                return db.execute("select notron_agents.reserve('run',%s)",(uuid.uuid4(),)).fetchone()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(reserve,range(8))),1)

    def test_timeout_reservation_survives_process_restart(self):
        self.begin()
        self.assertTrue(self.ledger.call('reserve','run',str(uuid.uuid4())))
        second=Ledger(DSN)
        try:
            self.assertFalse(second.call('reserve','run',str(uuid.uuid4())))
        finally:
            second.close()
        self.assertEqual(self.admin.execute('select sum(reserved) from notron_agents.calls where charged is null').fetchone()[0],1000000)

    def test_settlement_is_idempotent_and_does_not_refund_twice(self):
        self.begin()
        call=str(uuid.uuid4())
        self.ledger.call('reserve','run',call)
        self.assertTrue(self.ledger.call('settle','run',call,100))
        self.assertTrue(self.ledger.call('settle','run',call,100))
        self.assertFalse(self.ledger.call('settle','run',call,0))
        self.assertEqual(self.admin.execute('select sum(charged) from notron_agents.calls').fetchone()[0],100)

    def test_more_than_two_calls_per_day_refused(self):
        self.begin()
        for _ in range(2):
            call=str(uuid.uuid4())
            self.assertTrue(self.ledger.call('reserve','run',call))
            self.assertTrue(self.ledger.call('settle','run',call,100))
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))
        self.ledger.call('finish','run',Jsonb({'status':'done'}))
        self.assertFalse(self.ledger.call('claim','second','development'))

    def test_total_budget_includes_non_api_commitment(self):
        self.begin()
        self.admin.execute('update notron_agents.months set other_reserve=99500000')
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))

    def test_month_cap_with_earlier_charges(self):
        self.begin()
        self.admin.execute("insert into notron_agents.runs(id,role,slot,month,finished_at) select 'previous','development','previous',month,now() from notron_agents.months")
        self.admin.execute("insert into notron_agents.calls(id,run_id,charged) values(%s,'previous',79500000)",(uuid.uuid4(),))
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))

    def test_unapproved_month_refuses_development_and_release(self):
        self.admin.execute('update notron_agents.months set approved=false')
        self.assertFalse(self.ledger.call('claim','dev','development'))
        self.assertFalse(self.ledger.call('claim','rel','release'))

    def test_release_has_one_daily_slot_and_cannot_spend_model_money(self):
        self.ledger.db.execute('reset role')
        self.ledger.db.execute('set role notron_agent_release')
        self.assertTrue(self.ledger.call('claim','rel','release'))
        self.ledger.call('finish','rel',Jsonb({'status':'merged'}))
        self.assertFalse(self.ledger.call('claim','rel2','release'))
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            self.ledger.call('reserve','rel',str(uuid.uuid4()))

    def test_unsettled_prior_month_blocks_new_month(self):
        self.begin()
        self.admin.execute("insert into notron_agents.months(month,approved,other_reserve) select month-interval '1 month',true,20000000 from notron_agents.months")
        self.admin.execute("insert into notron_agents.runs(id,role,slot,month,finished_at) select 'old','development','old',min(month),now() from notron_agents.months")
        self.admin.execute("insert into notron_agents.calls(id,run_id) values(%s,'old')",(uuid.uuid4(),))
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))

    def test_kill_switch_expired_pricing_and_expired_lease_stop_spend(self):
        self.begin()
        self.admin.execute('update notron_agents.control set enabled=false')
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))
        self.admin.execute("update notron_agents.control set enabled=true,price_valid_until=now()-interval '1 second'")
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))
        self.admin.execute("update notron_agents.control set price_valid_until=now()+interval '1 day'")
        self.admin.execute("update notron_agents.runs set lease_until=now()-interval '1 second'")
        self.assertFalse(self.ledger.call('reserve','run',str(uuid.uuid4())))

    def test_over_envelope_settlement_halts_globally(self):
        self.begin()
        call=str(uuid.uuid4())
        self.ledger.call('reserve','run',call)
        self.assertFalse(self.ledger.call('settle','run',call,1000001))
        self.assertFalse(self.admin.execute('select enabled from notron_agents.control').fetchone()[0])
        self.assertTrue(self.admin.execute('select halted from notron_agents.months').fetchone()[0])

    def test_monitor_cannot_spend_or_read_raw_tables(self):
        self.ledger.db.execute('reset role')
        self.ledger.db.execute('set role notron_agent_monitor')
        for sql in ("select * from public.events", "select * from notron_agents.calls",
                    "update notron_agents.control set enabled=true",
                    "select notron_agents.reserve('run',gen_random_uuid())"):
            with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.ledger.db.execute(sql)

    def test_observer_returns_aggregates_and_deduplicates_incidents(self):
        self.admin.execute("truncate public.notron_batch_runs,public.events")
        self.admin.execute("insert into public.notron_batch_runs values(gen_random_uuid(),now(),now(),'{\"complete\":true}')")
        self.admin.execute("insert into public.events values(now(),true)")
        self.ledger.db.execute('reset role')
        self.ledger.db.execute('set role notron_agent_monitor')
        snapshot=self.ledger.call('observe')
        self.assertTrue(snapshot['news']['result']['complete'])
        for _ in range(2):
            self.ledger.call('record_incidents',Jsonb([{'code':'news_run_incomplete'}]))
        self.assertEqual(self.admin.execute('select count(*),max(occurrences) from notron_agents.incidents').fetchone(),(1,2))
        self.ledger.call('record_incidents',Jsonb([]))
        self.assertIsNotNone(self.admin.execute('select resolved_at from notron_agents.incidents').fetchone()[0])


if __name__=='__main__':
    unittest.main()
