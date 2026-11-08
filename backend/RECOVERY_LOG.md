# Bounded recovery operations

## 2026-11-08

After deploying the stale-X-cache isolation fix from PR #33, resume the incomplete
November 8 economy batch using the existing `--mode economy --resume` operation.
The operation must reuse the current daily ledger and selected story IDs, retain
the $1.50 daily total cap and all publication checks, and avoid overlapping runs.
Do not reset reservations or use the uncapped full pipeline.

This entry records the requested operation, not a successful publication result.
Use the workflow result and daily ledger to verify its outcome.
