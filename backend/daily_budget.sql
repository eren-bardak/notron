-- Apply once through the Supabase SQL editor / migration API, before activation.
-- No participant records or public policies are changed.
create table if not exists public.notron_daily_batches (
  day date primary key,
  charged bigint not null default 0 check (charged >= 0),
  reserved bigint not null default 0 check (reserved >= 0),
  halted boolean not null default false,
  completed boolean not null default false,
  event_ids bigint[] not null default '{}',
  active_run uuid,
  lease_until timestamptz,
  last_result jsonb
);
create table if not exists public.notron_batch_runs (
  id uuid primary key,
  day date not null references public.notron_daily_batches(day),
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  result jsonb
);
create table if not exists public.notron_api_reservations (
  id uuid primary key,
  run_id uuid not null references public.notron_batch_runs(id),
  amount bigint not null check (amount > 0),
  charged bigint check (charged >= 0),
  created_at timestamptz not null default now()
);
alter table public.notron_daily_batches enable row level security;
alter table public.notron_batch_runs enable row level security;
alter table public.notron_api_reservations enable row level security;
revoke all on public.notron_daily_batches, public.notron_batch_runs, public.notron_api_reservations from anon, authenticated;

create or replace function public.notron_daily_budget(
  p_operation text, p_run_id uuid, p_request_id uuid default null,
  p_amount bigint default null, p_event_ids bigint[] default null,
  p_result jsonb default null
) returns jsonb language plpgsql security definer set search_path = pg_catalog, public as $$
declare
  batch public.notron_daily_batches%rowtype;
  reservation public.notron_api_reservations%rowtype;
  batch_day date;
  request_limit bigint;
begin
  -- One lock serializes claims across days, machines, manual runs and retries.
  perform pg_advisory_xact_lock(6812382215);
  if p_operation in ('begin', 'begin_supplement') then
    batch_day := (now() at time zone 'Europe/Istanbul')::date;
    insert into public.notron_daily_batches(day) values(batch_day) on conflict do nothing;
    select * into batch from public.notron_daily_batches where day = batch_day for update;
    if batch.completed and p_operation = 'begin' then return jsonb_build_object('ok', true, 'skip', true, 'reason', 'daily batch already completed'); end if;
    if not batch.completed and p_operation = 'begin_supplement' then
      return jsonb_build_object('ok', false, 'reason', 'finish or resume the original daily batch first');
    end if;
    if batch.halted then return jsonb_build_object('ok', false, 'reason', 'budget requires investigation'); end if;
    if exists(select 1 from public.notron_daily_batches where lease_until > now()) then
      return jsonb_build_object('ok', false, 'reason', 'another batch holds the lease');
    end if;
    -- $1.50 total envelope. Keep $0.25 per attempt for runner compute.
    if batch.charged + batch.reserved + 250000 > 1500000 then
      return jsonb_build_object('ok', false, 'reason', 'daily budget exhausted');
    end if;
    insert into public.notron_batch_runs(id, day, result) values(p_run_id, batch_day,
      jsonb_build_object('supplement', p_operation = 'begin_supplement'));
    update public.notron_daily_batches set charged = charged + 250000,
      active_run = p_run_id, lease_until = now() + interval '30 minutes' where day = batch_day;
    return jsonb_build_object('ok', true, 'day', batch_day, 'event_ids', batch.event_ids);
  end if;

  select day into batch_day from public.notron_batch_runs where id = p_run_id;
  if batch_day is null then return jsonb_build_object('ok', false, 'reason', 'unknown batch run'); end if;
  select * into batch from public.notron_daily_batches where day = batch_day for update;

  if p_operation = 'settle' then
    select * into reservation from public.notron_api_reservations where id = p_request_id and run_id = p_run_id for update;
    if not found or p_amount is null or p_amount < 0 then
      return jsonb_build_object('ok', false, 'reason', 'invalid settlement');
    end if;
    if reservation.charged is not null then return jsonb_build_object('ok', true); end if;
    update public.notron_api_reservations set charged = p_amount where id = p_request_id;
    update public.notron_daily_batches set reserved = reserved - reservation.amount,
      charged = charged + p_amount, halted = halted or p_amount > reservation.amount where day = batch_day;
    return jsonb_build_object('ok', p_amount <= reservation.amount, 'reason', 'usage exceeded reviewed price envelope');
  end if;

  if batch.active_run is distinct from p_run_id or batch.lease_until <= now() then
    return jsonb_build_object('ok', false, 'reason', 'batch lease expired');
  end if;
  if p_operation = 'finish' then
    if exists(select 1 from public.notron_batch_runs where id = p_run_id and result->>'supplement' = 'true') then
      update public.notron_batch_runs set finished_at = now(), result = coalesce(p_result, '{}'::jsonb) || '{"supplement":true}'::jsonb where id = p_run_id;
      update public.notron_daily_batches set active_run = null, lease_until = null where day = batch_day;
      return jsonb_build_object('ok', true);
    end if;
    update public.notron_batch_runs set finished_at = now(), result = p_result where id = p_run_id;
    update public.notron_daily_batches set active_run = null, lease_until = null,
      completed = coalesce((p_result->>'complete')::boolean, false), last_result = p_result where day = batch_day;
    return jsonb_build_object('ok', true);
  end if;
  if batch.halted then return jsonb_build_object('ok', false, 'reason', 'budget halted'); end if;
  if p_operation = 'reserve' then
    if p_request_id is null or p_amount is null or p_amount not in (5000,50000,70000,900000) then
      return jsonb_build_object('ok', false, 'reason', 'invalid reservation');
    end if;
    select * into reservation from public.notron_api_reservations where id = p_request_id;
    -- A duplicate reservation must never authorize a second HTTP request.
    if found then return jsonb_build_object('ok', false, 'reason', 'duplicate request ID'); end if;
    if batch.charged + batch.reserved + p_amount > 1500000 then
      return jsonb_build_object('ok', false, 'reason', 'daily budget would be exceeded');
    end if;
    insert into public.notron_api_reservations(id,run_id,amount) values(p_request_id,p_run_id,p_amount);
    update public.notron_daily_batches set reserved = reserved + p_amount where day = batch_day;
    return jsonb_build_object('ok', true);
  end if;
  if p_operation = 'select' then
    if cardinality(batch.event_ids) = 0 then
      if p_event_ids is null or cardinality(p_event_ids) > 3
          or cardinality(p_event_ids) <> (select count(distinct id) from unnest(p_event_ids) as id) then
        return jsonb_build_object('ok', false, 'reason', 'invalid story selection');
      end if;
      update public.notron_daily_batches set event_ids = p_event_ids where day = batch_day;
      batch.event_ids := p_event_ids;
    end if;
    return jsonb_build_object('ok', true, 'event_ids', batch.event_ids);
  end if;
  return jsonb_build_object('ok', false, 'reason', 'unknown budget operation');
end;
$$;
revoke all on function public.notron_daily_budget(text,uuid,uuid,bigint,bigint[],jsonb) from public, anon, authenticated;
grant execute on function public.notron_daily_budget(text,uuid,uuid,bigint,bigint[],jsonb) to service_role;
