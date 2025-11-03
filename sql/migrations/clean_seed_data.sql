-- reset_dev_nexus.sql — destructive reset for local/CI only
begin;

-- make this session act as service_role (RLS allow)
select set_config('request.jwt.claims', '{"role":"service_role"}', true);

-- wipe data in correct dependency order (TRUNCATE ... CASCADE is easiest)
truncate table
  dev_nexus.phone_call_logs_stg,
  dev_nexus.campaign_activity,
  dev_nexus.campaign_step,
  dev_nexus.campaign_call_policy,
  dev_nexus.outcome,
  dev_nexus.handoff,
  dev_nexus.message,
  dev_nexus.event,
  dev_nexus.enrollment,
  dev_nexus.contact,
  dev_nexus.campaign,
  dev_nexus.providers,
  dev_nexus.template_variant,
  dev_nexus.template,
  dev_nexus.project,
  dev_nexus.tenant
restart identity cascade;

commit;
