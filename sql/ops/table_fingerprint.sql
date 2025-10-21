-- Deterministic fingerprints per table using stable ordering by a chosen key list
-- Falls back to created_at if id not found; errors if neither exists.
create schema if not exists ops;

create or replace function ops.table_fingerprint(
  _schema text,
  _table  text,
  _key_guess text[] default array['id','created_at']
)
returns table(row_count bigint, content_md5 text)
language plpgsql
as $$
declare
  key_col text;
  sql text;
begin
  -- choose an ordering key that exists on the table
  select k into key_col
  from unnest(_key_guess) as k
  where exists (
    select 1
    from information_schema.columns
    where table_schema=_schema and table_name=_table and column_name=k
  )
  limit 1;

  if key_col is null then
    raise exception 'No suitable key column found for %.% (tried: %)', _schema, _table, _key_guess;
  end if;

  sql := format($q$
    with t as (select * from %I.%I order by %I)
    select count(*)::bigint as row_count,
           md5(string_agg(md5(row_to_json(t.*)::text), ',' order by %I)) as content_md5
    from t
  $q$, _schema, _table, key_col, key_col);

  return query execute sql;
end;
$$;
