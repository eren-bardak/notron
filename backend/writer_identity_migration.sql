-- Legacy tables were created before Writer comments had an account reference.
-- Preserve all existing comments. Never guess or backfill their author identity.
alter table public.event_comments
  add column if not exists user_id uuid
  references auth.users(id) on delete set null;
