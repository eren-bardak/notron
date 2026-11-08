# Bounded recovery operations

## 2026-11-08

After deploying the stale-X-cache isolation fix from PR #33, resume the incomplete
November 8 economy batch using the existing `--mode economy --resume` operation.
The operation must reuse the current daily ledger and selected story IDs, retain
the $1.50 daily total cap and all publication checks, and avoid overlapping runs.
Do not reset reservations or use the uncapped full pipeline.

This entry records the requested operation, not a successful publication result.
Use the workflow result and daily ledger to verify its outcome.

## 2026-11-08 follow-up

The first recovery published one selected story and stopped safely before a new
research reservation. The approved total ceiling is now $3.25 for November 8 in
Europe/Istanbul only; all other dates remain $1.50. The guarded database migration
has been applied and date/boundary checks passed without altering ledger rows.
Resume the same remaining selected stories once under this cap, preserving all
editorial, publication, reservation and lease safeguards. This entry does not
claim completion; verify the workflow, ledger and public stories afterward.
