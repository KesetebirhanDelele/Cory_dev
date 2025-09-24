create or replace view dev_nexus.v_due_sms_followups as
select
  a.id   as activity_id,
  a.org_id,
  a.enrollment_id,
  a.generated_message,
  a.scheduled_at
from dev_nexus.campaign_activities a
where a.channel = 'sms'
  and a.status  = 'planned';