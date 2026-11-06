"""Offline decision preview only: never calls a provider, publishes or deploys.

Snapshots are supplied by an operator. They are NOT a trusted spend ledger or
authorization to execute work. A production adapter must reserve atomically.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

MONTHLY_LIMIT_CENTS = 10_000
API_LIMIT_CENTS = 8_000  # Leave $20 for compute/storage/taxes and uncertainty.


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timezone required')
    return result.astimezone(timezone.utc)


def cents(value):
    if type(value) is not int or value < 0:
        raise ValueError('Costs must be nonnegative integer cents')
    return value


def evaluate(snapshot, now):
    """Fail closed on stale/unknown spend; report news failures without retries."""
    alerts = []
    eligible = False
    try:
        observed = timestamp(snapshot['observed_at'])
        if not timedelta(0) <= now - observed <= timedelta(minutes=15):
            raise ValueError('Snapshot stale or from the future')
        budget = snapshot['agent_budget']
        if budget['month_utc'] != now.strftime('%Y-%m') or budget['costs_complete'] is not True:
            raise ValueError('Current monthly costs unknown')
        api = cents(budget['api_charged_cents']) + cents(budget['api_reserved_cents'])
        other = cents(budget['other_charged_cents']) + cents(budget['other_reserved_cents'])
        request = cents(budget['next_run_max_cents'])
        if request <= 0:
            raise ValueError('A bounded run reservation is required')
        eligible = api + request <= API_LIMIT_CENTS and api + other + request <= MONTHLY_LIMIT_CENTS
        if not eligible:
            alerts.append('agent_budget_exhausted')
        news = snapshot['news']
        if news['status'] not in ('completed', 'running', 'failed'):
            raise ValueError('Unknown news status')
        if news['status'] == 'failed':
            alerts.append('news_failed_no_automatic_retry')
        if news['status'] == 'running':
            age = now - timestamp(news['started_at'])
            if age < timedelta(0) or age > timedelta(minutes=30):
                alerts.append('news_lease_or_runtime_needs_inspection')
        # Source freshness is independent of whether a cron invocation succeeded.
        age = now - timestamp(news['latest_published_at'])
        if age < timedelta(0) or age > timedelta(hours=26):
            alerts.append('news_publication_stale_or_invalid')
    except (KeyError, TypeError, ValueError, AttributeError):
        eligible = False
        alerts.append('unknown_or_stale_evidence')
    return {
        'mode': 'offline_preview',
        'execution_authorized': False,
        'development_budget_candidate': eligible,
        'news_action': 'observe_existing_render_cron_only',
        'alerts': sorted(set(alerts)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    parser.add_argument('--now', help='ISO timestamp for reproducible fixture replay')
    args = parser.parse_args()
    try:
        now = timestamp(args.now) if args.now else datetime.now(timezone.utc)
        report = evaluate(json.loads(args.snapshot.read_text()), now)
    except (OSError, ValueError, TypeError, AttributeError):
        print(json.dumps({'mode': 'offline_preview', 'execution_authorized': False,
                          'alerts': ['invalid_snapshot']}))
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report['alerts'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
