# Nötron: selection and six-hour news pipeline

## Starting policy

`config/popularity.json` is shared by the Python pipeline and the web feed.
These are initial product settings, not weights calibrated against real traffic.

| Contribution | Points | Rule |
| --- | ---: | --- |
| P: cross-group coverage | 20 | Once, when coverage first reaches any two known groups: left, center, right |
| R: article | 5 | Each unique linked article, aged from its original publication time |
| Q: micro-comment | 1 | One active scored micro-comment per account per event |
| Q: ballot | 1 | One scored ballot per account per event, with at least one valid answer |
| S: Writer comment | 3 | One active scored Writer comment per account per event |

P is worth four articles, so reaching different media audiences matters. R keeps
reporting central. Q rewards participation without letting rapid, repeated actions
dominate. S gives the longer Writer contribution more weight than a micro-comment.
All answer directions receive equal points; skipping does not score. Answering
three questions still counts as one event ballot. Micro-comment protection
reactions are not event ballots and do not add ranking points.

Legacy Writer comments with no account identity earn no ranking points. The
scorer can read older comment tables without stopping the news pipeline. Apply
`backend/writer_identity_migration.sql` to an older database before accepting new
Writer submissions; it adds the missing nullable account reference and preserves
old rows without guessing their authors.

A single-group event can qualify without P. Unknown media labels receive no
group classification. Additional articles receive R; they never re-award P.
This measures breadth of coverage, not whether reporting is true or impartial.

## Decay and duplicate protection

For each valid contribution:

`points now = original points × 2^(-age in hours / 6)`

The score is the sum of those decayed contributions. There is no starting bonus.
For example, two freshly published articles from different groups start at 30:
after 6 hours, 15; after 12 hours, 7.5; after 18 hours, 3.75. A new article at
hour 6 adds 5 to the existing 15, making 20. It does not refresh old points.

The pipeline recomputes from original timestamps, rather than adding the previous
run's counts again. Re-running the same input does not inflate its score. The web
feed continues decaying the stored score between scheduled runs. New contributions
enter the ranking on the next successful scoring run.

Article IDs, canonical URLs (without tracking parameters), and repeated titles
from the same publisher are deduplicated. Ballot edits retain the original ballot
time. Per-account limits affect ranking credit, not how many valid contributions
can appear in discussion. Clearly marked sample answers and comments stay outside
the participation tables and never score. These limits reduce repetition; they
are not a complete defense against coordinated accounts.

## Qualification and placement

The clustering gates are: last 36 hours, at least two distinct publishers,
confidence at least 50, and articles referring to the same concrete occurrence.
Positive, neutral and negative developments qualify equally. There is no problem
requirement; legacy problem fields are descriptive metadata only. A new cluster must include
at least one new article. Clustering can consider up to 20 events in a run.

Before publication an event must have:

- A successful data-availability result, regardless of whether the news is positive or negative.
- At least two deduplicated publishers with articles from the last 36 hours.
- A sourced numerical series with at least two finite values.
- A ready deep analysis with exactly three nonempty questions.
- An event creation time within 36 hours and a current score of at least 5.

The top three qualifying events appear in Gündem. All remaining qualifying events
appear in Other Events, directly after Gündem. Ties use event ID. An event may
move between these tabs as ranking changes; it appears in only one at a time.
Below-threshold, expired, or incomplete events appear in neither tab. Old records
are retained in the database. There is no minimum number of displayed events.

The 5-point threshold lets smaller, corroborated stories qualify while removing
inactive stories through decay. The 36-hour event age limit is absolute: fresh
comments do not keep an old event displayed indefinitely. Active web views expire
cards and refresh the feed; Gündem is always capped at three cards.

## Execution and activation

From the project root:

```bash
python3 -m pip install -r backend/requirements.txt
python3 backend/run_pipeline.py --check
python3 backend/run_pipeline.py
```

The runner invokes, in order:

1. `rss_fetcher.py`
2. `clustering_news_enriched.py`
3. `update_event_popularity_v02.py`
4. `generate_event_deep_dives.py`

The arrows denote sequence, not shell output redirection. A failed script stops
the chain. Each script has a timeout; local overlapping runs are blocked on the
same Mac/Linux host. Prior successful steps are not rolled back after a failure.
The final stage publishes only complete, qualified analyses.

The provided `.github/workflows/news-pipeline.yml` is configured for 00:17, 06:17,
12:17 and 18:17 in Europe/Istanbul, plus manual runs and pipeline-code updates on
`main`. The first pipeline upload triggers a run automatically. The minute offset avoids
the busiest beginning of the hour. GitHub can delay or drop scheduled runs, so
these are scheduled start times, not a real-time guarantee. See the
[official schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

To activate it:

1. Put the Nötron source, including the workflow, on the default branch of its
   GitHub repository. A workflow saved only in the Sites source repository does
   not execute on GitHub.
2. In that repository's Actions secrets, configure `SUPABASE_URL`, `SUPABASE_KEY`
   (server write key), and `OPENAI_API_KEY`. Keep secrets out of source control
   and chat. Preserve an existing local `backend/.env` for local runs.
3. Enable Actions and manually run **Nötron news pipeline** once. Check all four
   stages and the final visible-event counts before relying on the schedule.
4. Use one production scheduler. GitHub concurrency prevents overlap within that
   repository; the local lock does not coordinate independent hosts.

The designated runner repository is `eren-bardak/notron`. A successful run requires
all three Actions secrets; missing configuration stops the job before it makes
requests or changes records. Publishing the website does not recompute database
scores or fetch news. The first successful pipeline run does that.

The production news feed contains only real database events; the former artificial
event feed and its URL switch have been removed. Real events show actual answers
and comments by default. A clearly labelled optional sample toggle still lets you
inspect charts with 20 synthetic answers; it never affects the live data.

After real traffic is available, review how many events qualify, how frequently
they change tabs, and how much of each score comes from reporting versus people.
Adjust the shared configuration from that evidence; changing weights requires a
new pipeline run and a website deployment to keep policy synchronized.
