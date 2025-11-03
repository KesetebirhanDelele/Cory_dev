-- === Config ===
with schema_name as (select 'dev_nexus'::text as n)

-- 1) Tables
select t.table_name
from information_schema.tables t, schema_name s
where t.table_schema = s.n and t.table_type = 'BASE TABLE'
order by t.table_name;

-- 2) Columns per table (order & types)
select c.table_name, c.column_name, c.ordinal_position, c.data_type,
       c.character_maximum_length, c.is_nullable, c.column_default
from information_schema.columns c, schema_name s
where c.table_schema = s.n
order by c.table_name, c.ordinal_position;

-- 3) Primary keys
select tc.table_name, kcu.column_name, kcu.ordinal_position
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name
 and tc.table_schema = kcu.table_schema
join schema_name s on s.n = tc.table_schema
where tc.constraint_type = 'PRIMARY KEY' and tc.table_schema = s.n
order by tc.table_name, kcu.ordinal_position;

-- 4) Foreign keys
select tc.table_name as child_table, kcu.column_name as child_column,
       ccu.table_name as parent_table, ccu.column_name as parent_column,
       rc.update_rule, rc.delete_rule
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
join information_schema.referential_constraints rc
  on rc.constraint_name = tc.constraint_name and rc.constraint_schema = tc.table_schema
join information_schema.constraint_column_usage ccu
  on ccu.constraint_name = rc.unique_constraint_name and ccu.constraint_schema = rc.unique_constraint_schema
join schema_name s on s.n = tc.table_schema
where tc.constraint_type = 'FOREIGN KEY' and tc.table_schema = s.n
order by child_table, child_column;

-- 5) Unique constraints
select tc.table_name, tc.constraint_name, string_agg(kcu.column_name, ', ' order by kcu.ordinal_position) as columns
from information_schema.table_constraints tc
join information_schema.key_column_usage kcu
  on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
join schema_name s on s.n = tc.table_schema
where tc.constraint_type = 'UNIQUE' and tc.table_schema = s.n
group by tc.table_name, tc.constraint_name
order by tc.table_name;

-- 6) Indexes (incl. unique, expressions, partial)
select t.relname as table_name,
       i.relname as index_name,
       idx.indisunique as is_unique,
       pg_get_indexdef(i.oid) as index_def
from pg_index idx
join pg_class i on i.oid = idx.indexrelid
join pg_class t on t.oid = idx.indrelid
join pg_namespace n on n.oid = t.relnamespace
join schema_name s on s.n = n.nspname
order by t.relname, i.relname;

-- 7) Views (plain views)
select v.table_name as view_name,
       pg_get_viewdef(format('%I.%I', v.table_schema, v.table_name)::regclass, true) as view_sql
from information_schema.views v, schema_name s
where v.table_schema = s.n
order by v.table_name;

-- 8) Materialized views
select mv.matviewname as matview_name, pg_get_viewdef(format('%I.%I', n.nspname, mv.matviewname)::regclass, true) as view_sql
from pg_matviews mv
join pg_namespace n on n.oid = mv.schemaname::regnamespace
join schema_name s on s.n = n.nspname
order by mv.matviewname;

-- 9) Routines (functions / stored procedures)
select r.routine_name, r.routine_type, r.data_type as return_type,
       pg_get_functiondef(format('%I.%I', r.specific_schema, r.routine_name)::regprocedure) as definition
from information_schema.routines r, schema_name s
where r.specific_schema = s.n
order by r.routine_name;

-- 10) Triggers
select e.event_object_table as table_name, t.trigger_name, t.action_timing, t.event_manipulation, t.action_statement
from information_schema.triggers t
join information_schema.triggered_update_columns e
  on t.trigger_name = e.trigger_name and t.trigger_schema = e.trigger_schema
join schema_name s on s.n = t.trigger_schema
where t.trigger_schema = s.n
group by table_name, t.trigger_name, t.action_timing, t.event_manipulation, t.action_statement
order by table_name, t.trigger_name;

-- 11) Sequences
select sequence_name
from information_schema.sequences s, schema_name sn
where s.sequence_schema = sn.n
order by sequence_name;

-- 12) Row-Level Security (RLS) policies
select pol.tablename as table_name,
       pol.policyname as policy_name,
       pol.cmd as applies_to,   -- SELECT/INSERT/UPDATE/DELETE/ALL
       pol.permissive,
       pg_get_expr(pol.qual, rel.oid)   as using_expr,
       pg_get_expr(pol.with_check, rel.oid) as check_expr
from pg_policies pol
join pg_class rel on rel.relname = pol.tablename and rel.relkind = 'r'
join pg_namespace n on n.oid = rel.relnamespace
join schema_name s on s.n = n.nspname
order by table_name, policy_name;

-- 13) Grants (who can do what)
select grantee, table_name, privilege_type, is_grantable
from information_schema.role_table_grants g, schema_name s
where g.table_schema = s.n
order by table_name, grantee, privilege_type;

-- To export result to CSV
-- \copy (SELECT ...your query...) TO 'schema_tables.csv' CSV HEADER