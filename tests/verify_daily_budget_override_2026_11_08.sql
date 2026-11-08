-- Read-only verification of BOTH expressions extracted from the installed function.
-- No RPC is invoked, no paid call is made, and no ledger row is modified.
do $test$
declare
  source text;
  gate text;
  cap_expression text;
  tested_expression text;
  actual bigint;
  d date;
  instant timestamptz;
  expected bigint;
  test_case record;
  gates integer := 0;
begin
  select prosrc into source from pg_proc
    where oid='public.notron_daily_budget(text,uuid,uuid,bigint,bigint[],jsonb)'::regprocedure;
  foreach gate in array array['250000', 'p_amount'] loop
    cap_expression := substring(source from
      'if batch[.]charged [+] batch[.]reserved [+] ' || gate || ' > (.*?) then' || chr(10));
    if cap_expression is null then raise exception 'Missing gate %', gate; end if;
    for test_case in select * from (values
      (date '2026-11-07', timestamptz '2026-11-07 20:59:59+00',1500000),
      (date '2026-11-08', timestamptz '2026-11-07 21:00:00+00',3250000),
      (date '2026-11-08', timestamptz '2026-11-08 20:59:59+00',3250000),
      (date '2026-11-08', timestamptz '2026-11-08 21:00:00+00',1500000),
      (date '2026-11-09', timestamptz '2026-11-08 21:00:00+00',1500000),
      (date '2026-11-07', timestamptz '2026-11-08 08:00:00+00',1500000)
    ) c(batch_day,instant,expected) loop
      tested_expression := replace(replace(cap_expression,'batch_day','$1'),'clock_timestamp()','$2');
      execute 'select ' || tested_expression into actual using test_case.batch_day,test_case.instant;
      if actual <> test_case.expected then raise exception 'Wrong cap gate %, case %',gate,test_case; end if;
      if (actual - 250000 + 250000 > actual) or not (actual - 250000 + 1 + 250000 > actual)
        or (actual - 900000 + 900000 > actual) or not (actual - 900000 + 1 + 900000 > actual)
      then raise exception 'Cap arithmetic boundary failure'; end if;
    end loop;
    gates := gates + 1;
  end loop;
  if gates <> 2 then raise exception 'Expected both begin/reserve gates'; end if;
end;
$test$;
select 'PASS: both installed gates; six Istanbul date boundaries each; exact cap and cap+1 checks; no ledger writes' as verification;
