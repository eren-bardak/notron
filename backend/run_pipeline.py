"""One fail-fast run, suitable for the provided six-hour GitHub schedule."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
STEPS = ['rss_fetcher.py', 'clustering_news_enriched.py', 'update_event_popularity_v02.py', 'generate_event_deep_dives.py', 'news_narration.py']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='Check credentials and script paths without making requests.')
    args = parser.parse_args()
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
            subprocess.run([sys.executable, str(BACKEND / script)], cwd=BACKEND, check=True, timeout=9000)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f'Pipeline stopped: {error}', file=sys.stderr)
        return 1
    finally:
        lock.close()
    print('Pipeline finished successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
