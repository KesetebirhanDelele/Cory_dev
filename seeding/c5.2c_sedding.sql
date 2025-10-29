-- Mock campaign: Admissions Outreach
insert into public.campaigns (name, max_attempts, policy)
values ('Admissions Outreach', 3, '{"quiet_hours":[22,6],"timezone":"UTC"}')
returning id;


-- Replace {{campaign_id}} below with the returned UUID from previous insert
insert into public.campaign_steps (campaign_id, step_index, channel, prompt_template, wait_seconds)
values
  ('ce34637e-726c-4fc8-af1f-b3e53a0ea58a', 1, 'voice', 'Call {{name}} and invite them to discuss their program interest.', 10),
  ('ce34637e-726c-4fc8-af1f-b3e53a0ea58a', 2, 'sms', 'Hi {{name}}, this is Cory Admissions. Are you free to chat?', 20),
  ('ce34637e-726c-4fc8-af1f-b3e53a0ea58a', 3, 'email', 'Subject: Explore your program options\n\nHi {{name}}, we’d love to help you get started.', 30),
  ('ce34637e-726c-4fc8-af1f-b3e53a0ea58a', 4, 'escalate', 'Escalate {{name}} to human advisor for follow-up.', 0);

  insert into public.leads (name, phone, email)
values
  ('Alice Brown', '+15555550011', 'alice.brown@example.com'),
  ('Bob Green', '+15555550012', 'bob.green@example.com'),
  ('Carlos Diaz', '+15555550013', 'carlos.diaz@example.com');

-- Replace {{campaign_id}} with same ID
insert into public.campaign_enrollments (campaign_id, lead_id, next_run_at)
select 'ce34637e-726c-4fc8-af1f-b3e53a0ea58a', id, now()
from public.leads;