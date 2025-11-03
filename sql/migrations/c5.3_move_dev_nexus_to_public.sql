-- ===============================================
-- 00xx_move_dev_nexus_to_public.sql
-- Move all app tables from dev_nexus to public schema
-- ===============================================

BEGIN;

-- ✅ Core tenant and system tables
ALTER TABLE IF EXISTS dev_nexus.tenant SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.project SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.providers SET SCHEMA public;

-- ✅ Campaign-related tables
ALTER TABLE IF EXISTS dev_nexus.campaign SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.campaign_step SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.campaign_call_policy SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.campaign_activity SET SCHEMA public;

-- ✅ Communication & interaction tracking
ALTER TABLE IF EXISTS dev_nexus.message SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.handoff SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.outcome SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.event SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.contact SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.enrollment SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.phone_call_logs_stg SET SCHEMA public;

-- ✅ Templates and documents
ALTER TABLE IF EXISTS dev_nexus.template SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.template_variant SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.docs SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.doc_chunks SET SCHEMA public;

-- ✅ KPI and telemetry views / metrics
ALTER TABLE IF EXISTS dev_nexus.telemetry_view SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.telemetry_view_enriched SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.kpi_interaction_stages SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.kpi_latency_p95 SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.kpi_deliverability_by_channel SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.kpi_response_by_variant SET SCHEMA public;

-- ✅ Materialized / logical views
ALTER TABLE IF EXISTS dev_nexus.v_due_actions SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.v_due_sms_followups SET SCHEMA public;
ALTER TABLE IF EXISTS dev_nexus.v_variant_attribution SET SCHEMA public;

COMMIT;
