-- Bootstrap for a PRIVATE schema in the existing PostgreSQL database.
-- Apply to a disposable database first. This is not a deployed migration.
-- A DBA must approve each month's all-in non-API reserve before enabling work.
begin;
create schema if not exists notron_agents;
revoke all on schema notron_agents from public;
do $$ begin
  if not exists(select from pg_roles where rolname='notron_agent_dev') then
    create role notron_agent_dev nologin;
  end if;
  if not exists(select from pg_roles where rolname='notron_agent_monitor') then
    create role notron_agent_monitor nologin;
  end if;
  if not exists(select from pg_roles where rolname='notron_agent_release') then
    create role notron_agent_release nologin;
  end if;
end $$;
create table if not exists notron_agents.control (
  id boolean primary key default true check(id),
  enabled boolean not null default false,
  price_valid_until timestamptz not null default '-infinity'
);
insert into notron_agents.control(id) values(true) on conflict do nothing;
create table if not exists notron_agents.months (
  month date primary key check(extract(day from month)=1),
  approved boolean not null default false,
  -- microdollars: 100000000 = $100. Includes taxes and all other costs.
  other_reserve bigint not null check(other_reserve between 20000000 and 100000000),
  halted boolean not null default false
);
create table if not exists notron_agents.runs (
  id text primary key,
  role text not null check(role in ('development','monitor','release')),
  slot text not null,
  month date not null references notron_agents.months(month),
  started_at timestamptz not null default now(),
  lease_until timestamptz not null default now()+interval '25 minutes',
  finished_at timestamptz,
  result jsonb,
  unique(role,slot)
);
alter table notron_agents.runs drop constraint if exists runs_role_check;
alter table notron_agents.runs add constraint runs_role_check check(role in ('development','monitor','release'));
create table if not exists notron_agents.calls (
  id uuid primary key,
  run_id text not null references notron_agents.runs(id),
  reserved bigint not null default 1000000 check(reserved=1000000),
  charged bigint check(charged>=0),
  created_at timestamptz not null default now()
);
create index if not exists agent_calls_run on notron_agents.calls(run_id);
create table if not exists notron_agents.incidents (
  fingerprint text primary key,
  first_seen timestamptz not null default now(),
  last_seen timestamptz not null default now(),
  occurrences integer not null default 1,
  resolved_at timestamptz,
  details jsonb not null
);
alter table notron_agents.control enable row level security;
alter table notron_agents.months enable row level security;
alter table notron_agents.runs enable row level security;
alter table notron_agents.calls enable row level security;
alter table notron_agents.incidents enable row level security;
revoke all on all tables in schema notron_agents from public, notron_agent_dev, notron_agent_monitor, notron_agent_release;

create or replace function notron_agents.claim(p_id text, p_role text)
returns boolean language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
declare m date := date_trunc('month', now() at time zone 'UTC')::date; s text;
begin
  perform pg_advisory_xact_lock(6812382216);
  if p_role not in ('development','monitor','release') or length(p_id) not between 1 and 150 then return false; end if;
  if not pg_has_role(coalesce(nullif(current_setting('role'),'none'),session_user), case p_role when 'development' then 'notron_agent_dev' when 'monitor' then 'notron_agent_monitor' else 'notron_agent_release' end, 'member') then return false; end if;
  if not exists(select from notron_agents.control where enabled) then return false; end if;
  if not exists(select from notron_agents.months where month=m and approved and not halted) then return false; end if;
  s := to_char(now() at time zone 'UTC', case when p_role='monitor' then 'YYYY-MM-DD-HH24' else 'YYYY-MM-DD' end);
  if exists(select from notron_agents.runs where role=p_role and finished_at is null and lease_until>now()) then return false; end if;
  insert into notron_agents.runs(id,role,slot,month) values(p_id,p_role,s,m) on conflict do nothing;
  return found;
end $$;

create or replace function notron_agents.reserve(p_run text, p_call uuid)
returns boolean language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
declare r notron_agents.runs%rowtype; m notron_agents.months%rowtype; used bigint;
begin
  perform pg_advisory_xact_lock(6812382216);
  select * into r from notron_agents.runs where id=p_run;
  if not found or r.role<>'development' or r.finished_at is not null or r.lease_until<=now()
     or r.month<>date_trunc('month',now() at time zone 'UTC')::date then return false; end if;
  if not exists(select from notron_agents.control where enabled and price_valid_until>now()) then return false; end if;
  select * into m from notron_agents.months where month=r.month;
  if not m.approved or m.halted then return false; end if;
  -- Any uncertain request stops new spending, including across month rollover.
  if exists(select from notron_agents.calls where charged is null) then return false; end if;
  if exists(select from notron_agents.calls where id=p_call) then return false; end if;
  if (select count(*) from notron_agents.calls where run_id=p_run)>=2 then return false; end if;
  select coalesce(sum(coalesce(c.charged,c.reserved)),0) into used
    from notron_agents.calls c join notron_agents.runs rr on rr.id=c.run_id where rr.month=r.month;
  if used+1000000>80000000 or used+m.other_reserve+1000000>100000000 then return false; end if;
  insert into notron_agents.calls(id,run_id) values(p_call,p_run);
  return true;
end $$;

create or replace function notron_agents.settle(p_run text,p_call uuid,p_charge bigint)
returns boolean language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
declare c notron_agents.calls%rowtype;
begin
  perform pg_advisory_xact_lock(6812382216);
  select * into c from notron_agents.calls where id=p_call and run_id=p_run;
  if not found or p_charge is null or p_charge<0 then return false; end if;
  if c.charged is not null then return c.charged=p_charge; end if;
  update notron_agents.calls set charged=p_charge where id=p_call;
  if p_charge>c.reserved then
    update notron_agents.months set halted=true where month=(select month from notron_agents.runs where id=p_run);
    update notron_agents.control set enabled=false;
    return false;
  end if;
  return true;
end $$;

create or replace function notron_agents.finish(p_run text,p_result jsonb)
returns void language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
begin
  if octet_length(p_result::text)>16000 then raise exception 'result too large'; end if;
  update notron_agents.runs set finished_at=now(),result=p_result
    where id=p_run and finished_at is null
      and pg_has_role(coalesce(nullif(current_setting('role'),'none'),session_user),
        case role when 'development' then 'notron_agent_dev' when 'monitor' then 'notron_agent_monitor' else 'notron_agent_release' end, 'member');
end $$;

create or replace function notron_agents.observe()
returns jsonb language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
declare latest record; result jsonb; freshness timestamptz;
begin
  -- Only aggregate operational fields leave the database, never participant data.
  select b.started_at,b.finished_at,b.result into latest from public.notron_batch_runs b order by b.started_at desc limit 1;
  select max(created_at) into freshness from public.events where is_visible=true;
  result := jsonb_build_object('observed_at',now(),'news',jsonb_build_object(
    'started_at',latest.started_at,'finished_at',latest.finished_at,'result',latest.result,
    'latest_visible_created_at',freshness),
    'unsettled_calls',(select count(*) from notron_agents.calls where charged is null),
    'enabled',(select enabled from notron_agents.control));
  return result;
end $$;

create or replace function notron_agents.record_incidents(p_incidents jsonb)
returns integer language plpgsql security definer set search_path=pg_catalog,notron_agents as $$
declare item jsonb; added integer:=0; n integer;
begin
  if jsonb_typeof(p_incidents)<>'array' or jsonb_array_length(p_incidents)>20 or octet_length(p_incidents::text)>16000 then
    raise exception 'invalid incident report';
  end if;
  perform pg_advisory_xact_lock(6812382217);
  update notron_agents.incidents set resolved_at=now() where resolved_at is null
    and not exists(select 1 from jsonb_array_elements(p_incidents) where value->>'code'='monitor_evidence_unavailable')
    and fingerprint not in(select value->>'code' from jsonb_array_elements(p_incidents));
  for item in select value from jsonb_array_elements(p_incidents) loop
    if item->>'code' !~ '^[a-z_]{1,80}$' then raise exception 'invalid incident code'; end if;
    insert into notron_agents.incidents(fingerprint,details) values(item->>'code',item)
      on conflict(fingerprint) do update set last_seen=now(),occurrences=notron_agents.incidents.occurrences+1,
        resolved_at=null, details=excluded.details;
    get diagnostics n = row_count;
    added := added+n;
  end loop;
  return added;
end $$;

revoke execute on all functions in schema notron_agents from public;
grant usage on schema notron_agents to notron_agent_dev,notron_agent_monitor,notron_agent_release;
grant execute on function notron_agents.claim(text,text),notron_agents.finish(text,jsonb) to notron_agent_dev,notron_agent_monitor,notron_agent_release;
grant execute on function notron_agents.reserve(text,uuid),notron_agents.settle(text,uuid,bigint) to notron_agent_dev;
grant execute on function notron_agents.observe(),notron_agents.record_incidents(jsonb) to notron_agent_monitor;
commit;
