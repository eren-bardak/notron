"""Run offline tests, a bounded economy refresh, or the full news pipeline."""
import argparse
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
STEPS = ['rss_fetcher.py', 'clustering_news_enriched.py', 'update_event_popularity_v02.py', 'generate_event_briefs.py', 'generate_event_deep_dives.py']


def pipeline_environment(mode):
    env = dict(os.environ)
    env['NOTRON_PIPELINE_MODE'] = mode
    if mode == 'economy':
        model = env.get('OPENAI_ECONOMY_MODEL') or 'gpt-6-luna'
        env.pop('MAX_CLUSTER_EVENTS', None)
        env.update(MAX_CLUSTER_ARTICLES='300', MAX_DEEP_DIVES_PER_RUN='3',
                   OPENAI_EVENT_MODEL=model, OPENAI_DEEP_DIVE_MODEL=model)
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['test', 'economy', 'full'], default='full')
    parser.add_argument('--check', action='store_true', help='Check credentials and script paths without making requests.')
    parser.add_argument('--resume', action='store_true', help='Resume scoring and unfinished selected stories using the same daily budget.')
    parser.add_argument('--scores-only', action='store_true', help='Recompute scores and publication without paid API calls.')
    parser.add_argument('--supplement', action='store_true', help='Refresh category coverage with text-only briefs within the original daily budget.')
    parser.add_argument('--x-only', action='store_true', help='Refresh X measurements using the remaining shared daily budget; no news generation.')
    args = parser.parse_args()
    if (args.resume or args.scores_only or args.supplement or args.x_only) and args.mode != 'economy':
        parser.error('Maintenance requires --mode economy.')
    if sum([args.resume, args.scores_only, args.supplement, args.x_only]) > 1:
        parser.error('Choose one maintenance operation.')
    if args.mode == 'test':
        if args.check:
            print('Offline test mode. No API credentials are needed.')
            return 0
        # Never load .env or pass live credentials into offline tests.
        env = dict(os.environ)
        for key in ('OPENAI_API_KEY', 'SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_ANON_KEY', 'X_BEARER_TOKEN', 'YOUTUBE_API_KEY', 'YOUTUBE_DATA_API_KEY'):
            env.pop(key, None)
        return subprocess.run(
            [sys.executable, str(BACKEND / 'offline_tests.py')],
            cwd=BACKEND.parent, env=env, check=False, timeout=600,
        ).returncode
    if (BACKEND / '.env').exists():
        from dotenv import load_dotenv
        load_dotenv(BACKEND / '.env')
    required = ('SUPABASE_URL', 'SUPABASE_KEY') if args.scores_only else ('SUPABASE_URL', 'SUPABASE_KEY', 'OPENAI_API_KEY')
    if args.x_only:
        required = (*required, 'X_BEARER_TOKEN')
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print('Pipeline not started. Missing configuration: ' + ', '.join(missing), file=sys.stderr)
        return 2
    for script in STEPS:
        if not (BACKEND / script).is_file():
            print(f'Missing script: {script}', file=sys.stderr)
            return 2
    if args.check:
        print('Configuration is present. No requests or database changes were made.')
        return 0
    env = pipeline_environment(args.mode)
    steps = ['update_event_popularity_v02.py', 'generate_event_deep_dives.py'] if args.resume or args.scores_only else STEPS
    if args.supplement:
        steps = ['rss_fetcher.py', 'clustering_news_enriched.py', 'update_event_popularity_v02.py', 'generate_event_briefs.py']
    if args.x_only:
        steps = []
    if args.scores_only:
        # Scoring can reuse cached X measurements, but cannot buy new ones.
        env['X_BEARER_TOKEN'] = ''
        env['NOTRON_RUN_ID'] = ''
    if args.mode == 'economy' and env['OPENAI_EVENT_MODEL'] != 'gpt-6-luna':
        print('Daily budget pricing is verified only for gpt-6-luna.', file=sys.stderr)
        return 2
    print(f'Pipeline mode: {args.mode}', flush=True)
    # Prevent cron/manual runs on this same host from overlapping.
    import fcntl
    lock = (BACKEND / '.pipeline.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('A pipeline run is already active on this host.')
        lock.close()
        return 1
    db = None
    batch_started = False
    outcome = {'complete': False, 'reason': 'pipeline did not complete'}
    stage_failures = []
    paid_blocked = False
    deadline = time.monotonic() + 19 * 60
    try:
        if args.mode == 'economy' and not args.scores_only:
            from supabase import create_client
            from daily_budget import ledger
            db = create_client(env['SUPABASE_URL'], env['SUPABASE_KEY'])
            env['NOTRON_RUN_ID'] = str(uuid.uuid4())
            os.environ['NOTRON_RUN_ID'] = env['NOTRON_RUN_ID']
            claim = ledger(db, 'begin_supplement' if args.supplement or args.x_only else 'begin')
            if claim.get('skip'):
                print(claim.get('reason', 'Daily batch already completed.'), flush=True)
                return 0
            batch_started = True
        for script in steps:
            if paid_blocked and script in ('generate_event_briefs.py', 'generate_event_deep_dives.py'):
                continue
            print(f'Running {script}', flush=True)
            remaining = max(1, deadline - time.monotonic()) if args.mode == 'economy' else 9000
            command = [sys.executable, str(BACKEND / script)]
            env['NOTRON_X_PHASE'] = 'deferred'
            if args.scores_only and script == 'generate_event_deep_dives.py':
                command.append('--validate-only')
            try:
                subprocess.run(command, cwd=BACKEND, env=env, check=True, timeout=remaining)
            except subprocess.CalledProcessError as error:
                # Story preparation is independent of publishing/social refresh.
                # Keep the run incomplete for a same-budget resume, but drain later stages.
                if script not in ('generate_event_briefs.py', 'generate_event_deep_dives.py') or args.scores_only:
                    raise
                stage_failures.append({'stage': script, 'returncode': error.returncode})
                if error.returncode == 3:
                    paid_blocked = True
                print(f'Story stage incomplete; continuing ready stories | stage={script}', flush=True)
        if args.mode == 'economy' and not args.scores_only and not paid_blocked:
            env['NOTRON_X_PHASE'] = 'measure'
            subprocess.run([sys.executable, str(BACKEND / 'update_event_popularity_v02.py')], cwd=BACKEND,
                           env=env, check=True, timeout=max(1, deadline-time.monotonic()))
        if args.mode == 'economy' and not args.scores_only:
            subprocess.run([sys.executable, str(BACKEND / 'generate_event_deep_dives.py'), '--validate-only'],
                           cwd=BACKEND, env=env, check=True, timeout=max(1, deadline-time.monotonic()))
        outcome = {'complete': not stage_failures, 'failed_stages': stage_failures, 'reason': 'X refresh pass finished within shared budget' if args.x_only else 'selected cross-spectrum stories passed publication checks'}
        if stage_failures:
            outcome['reason'] = 'story_preparation_incomplete_publication_and_social_refresh_finished'
    except Exception as error:
        outcome['reason'] = type(error).__name__
        print(f'Pipeline stopped: {error}', file=sys.stderr)
        return 1
    finally:
        if batch_started:
            try:
                ledger(db, 'finish', p_result=outcome)
            except Exception as error:
                outcome['complete'] = False
                print(f'Could not finalize shared batch state: {type(error).__name__}', file=sys.stderr)
        lock.close()
        os.environ.pop('NOTRON_RUN_ID', None)
    if not outcome['complete']:
        return 1
    print('Pipeline finished successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

