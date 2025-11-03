-- =====================================================
-- 🧩 CORY DATABASE INVENTORY (everything in one query)
-- =====================================================

WITH 
-- 1️⃣ TABLES + COLUMNS
tables AS (
  SELECT 
    'TABLE' AS object_type,
    t.table_name AS parent_name,
    c.column_name AS object_name,
    c.data_type,
    c.is_nullable,
    c.column_default AS default_value
  FROM information_schema.tables t
  JOIN information_schema.columns c 
    ON c.table_name = t.table_name AND c.table_schema = t.table_schema
  WHERE t.table_schema = 'public' AND t.table_type = 'BASE TABLE'
),

-- 2️⃣ VIEWS + COLUMNS
views AS (
  SELECT 
    'VIEW' AS object_type,
    v.table_name AS parent_name,
    c.column_name AS object_name,
    c.data_type,
    c.is_nullable,
    NULL AS default_value
  FROM information_schema.views v
  JOIN information_schema.columns c 
    ON c.table_name = v.table_name AND c.table_schema = v.table_schema
  WHERE v.table_schema = 'public'
),

-- 3️⃣ INDEXES
indexes AS (
  SELECT 
    'INDEX' AS object_type,
    tablename AS parent_name,
    indexname AS object_name,
    NULL AS data_type,
    NULL AS is_nullable,
    NULL AS default_value
  FROM pg_indexes
  WHERE schemaname = 'public'
),

-- 4️⃣ FUNCTIONS
functions AS (
  SELECT 
    'FUNCTION' AS object_type,
    specific_name AS parent_name,
    routine_name AS object_name,
    data_type AS return_type,
    NULL AS is_nullable,
    NULL AS default_value
  FROM information_schema.routines
  WHERE specific_schema = 'public'
),

-- 5️⃣ TRIGGERS
triggers AS (
  SELECT 
    'TRIGGER' AS object_type,
    event_object_table AS parent_name,
    trigger_name AS object_name,
    event_manipulation AS data_type,
    action_timing AS is_nullable,
    action_statement AS default_value
  FROM information_schema.triggers
  WHERE trigger_schema = 'public'
),

-- 6️⃣ RLS
rls AS (
  SELECT 
    'RLS' AS object_type,
    c.relname AS parent_name,
    CASE WHEN c.relrowsecurity THEN 'ENABLED' ELSE 'DISABLED' END AS object_name,
    NULL AS data_type,
    NULL AS is_nullable,
    NULL AS default_value
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'public' AND c.relkind = 'r'
),

-- 7️⃣ POLICIES
policies AS (
  SELECT 
    'POLICY' AS object_type,
    tablename AS parent_name,
    policyname AS object_name,
    cmd AS data_type,
    permissive::text AS is_nullable,
    CONCAT('USING: ', COALESCE(qual, 'none'), ' | CHECK: ', COALESCE(with_check, 'none')) AS default_value
  FROM pg_policies
  WHERE schemaname = 'public'
)

-- 🧾 Combine everything
SELECT * FROM tables
UNION ALL
SELECT * FROM views
UNION ALL
SELECT * FROM indexes
UNION ALL
SELECT * FROM functions
UNION ALL
SELECT * FROM triggers
UNION ALL
SELECT * FROM rls
UNION ALL
SELECT * FROM policies
ORDER BY object_type, parent_name, object_name;
