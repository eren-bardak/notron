"""Run offline tests, a bounded economy refresh, or the full news pipeline."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
STEPS = ['rss_fetcher.py', 'clustering_news_enriched.py', 'update_event_popularity_v02.py', 'generate_event_deep_dives.py']


def pipeline_environment(mode):
    env = dict(os.environ)
    env['NOTRON_PIPELINE_MODE'] = mode
    if mode == 'economy':
        model = env.get('OPENAI_ECONOMY_MODEL') or 'gpt-6-luna'
        env.update(MAX_CLUSTER_ARTICLES='80', MAX_CLUSTER_EVENTS='3', MAX_DEEP_DIVES_PER_RUN='1',
                   OPENAI_EVENT_MODEL=model, OPENAI_DEEP_DIVE_MODEL=model)
    return env


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['test', 'economy', 'full'], default='full')
    parser.add_argument('--check', action='store_true', help='Check credentials and script paths without making requests.')
    args = parser.parse_args()
    if args.mode == 'test':
        if args.check:
            print('Offline test mode. No API credentials are needed.')
            return 0
        # Never load .env or pass live credentials into offline tests.
        env = dict(os.environ)
        for key in ('OPENAI_API_KEY', 'SUPABASE_URL', 'SUPABASE_KEY', 'SUPABASE_ANON_KEY'):
            env.pop(key, None)
        return subprocess.run(
            [sys.executable, str(BACKEND / 'offline_tests.py')],
            cwd=BACKEND.parent, env=env, check=False, timeout=600,
        ).returncode
    if (BACKEND / '.env').exists():
        from dotenv import load_dotenv
        load_dotenv(BACKEND / '.env')
    missing = [key for key in ('SUPABASE_URL', 'SUPABASE_KEY', 'OPENAI_API_KEY') if not os.getenv(key)]
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
    print(f'Pipeline mode: {args.mode}', flush=True)
    # Prevent cron/manual runs on this same host from overlapping.
    import fcntl
    lock = (BACKEND / '.pipeline.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print('A pipeline run is already active on this host.')
        return 1
    try:
        for script in STEPS:
            print(f'Running {script}', flush=True)
            subprocess.run([sys.executable, str(BACKEND / script)], cwd=BACKEND, env=env, check=True, timeout=9000)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f'Pipeline stopped: {error}', file=sys.stderr)
        return 1
    finally:
        lock.close()
    print('Pipeline finished successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

