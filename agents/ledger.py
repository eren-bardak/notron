"""Inert database adapter for the disposable ledger integration tests.

Extracted without behavior changes from PR31 at
ab86126e7035fac5165793eca96c80c958a2ec7b (agents/cloud_agents.py).
No provider client, controller, scheduler, environment loading or entrypoint.
This is the low-level adapter, not a production connection/activation path;
PR31's production caller applies its separate TLS and activation guards.
"""
import psycopg


class Stopped(RuntimeError):
    pass


class Ledger:
    def __init__(self, dsn):
        # Require TLS in cloud; local integration tests explicitly use sslmode=disable.
        self.db = psycopg.connect(dsn, connect_timeout=10, autocommit=True)
        self.db.execute("set statement_timeout='15s'")
        self.db.execute("set lock_timeout='5s'")

    def call(self, function, *args):
        if function not in {'claim', 'reserve', 'settle', 'finish', 'observe', 'record_incidents'}:
            raise Stopped('unknown ledger operation')
        placeholders = ','.join(['%s']*len(args))
        return self.db.execute(f'SELECT notron_agents.{function}({placeholders})', args).fetchone()[0]

    def close(self):
        self.db.close()
