"""Run every ledger integration test; missing configuration or skips must fail CI."""
import os
from pathlib import Path
import sys
import unittest

EXPECTED_TESTS = 19


def main():
    if not os.environ.get('AGENT_TEST_DATABASE_URL'):
        print('AGENT_TEST_DATABASE_URL is required for disposable local PostgreSQL tests.', file=sys.stderr)
        return 2
    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parent / 'tests'), pattern='test_ledger_postgres.py')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or result.testsRun != EXPECTED_TESTS:
        print(f'Expected {EXPECTED_TESTS} executed tests and no skips; ran {result.testsRun}, skipped {len(result.skipped)}.', file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
