-- Surgical migration: retain the deployed ledger's budget, temporary override,
-- grants, lease, retry state and reservations. Never reset today's selection.
begin;
do $migration$
declare definition text;
begin
  definition := pg_get_functiondef('public.notron_daily_budget(text,uuid,uuid,bigint,bigint[],jsonb)'::regprocedure);
  if position('p_event_ids is null or cardinality(p_event_ids) > 3' in definition) = 0 then
    raise exception 'Unexpected ledger selection guard; inspect before migrating';
  end if;
  definition := replace(definition, 'p_event_ids is null or cardinality(p_event_ids) > 3', 'p_event_ids is null or cardinality(p_event_ids) > 70
          or exists (select 1 from unnest(p_event_ids) as selected(id)
            left join public.events e on e.id = selected.id where e.id is null)
          or exists (select 1 from public.events e where e.id = any(p_event_ids)
            group by case when e.category in (''politics'',''finance'',''sports'',''magazine'',''technology'',''entertainment'') then e.category
              when e.category = ''economy'' then ''finance''
              when e.category = ''technology_science'' then ''technology''
              when e.category = ''culture'' then ''entertainment'' else ''general'' end
            having count(*) > 10)');
  execute definition;
end;
$migration$;
commit;
