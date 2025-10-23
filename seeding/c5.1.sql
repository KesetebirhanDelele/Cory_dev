-- programs
insert into programs(code,name,active) values
 ('NURS-BS','Bachelor of Science in Nursing',true),
 ('BUS-BA','Bachelor of Arts in Business',true)
on conflict (code) do nothing;

-- rules (version 1)
insert into persona_rules(version, rule_name, priority, dsl) values
 (1,'Nursing west coast',10,'{
   "if":{"interest_contains":"nursing","zip_in":["9*"]},
   "then":{"program_code":"NURS-BS","score":0.92}
 }'::jsonb),
 (1,'Business default',50,'{
   "if":{"interest_contains":"business"},
   "then":{"program_code":"BUS-BA","score":0.80}
 }'::jsonb);

alter table leads add column if not exists zip text;
alter table leads add column if not exists interest text;

-- test lead
insert into leads(id,email,phone,zip,interest)
values ('00000000-0000-0000-0000-000000000001','test@example.edu','5551112222','94107','nursing')
on conflict (id) do nothing;

-- programs
insert into programs(code,name,active) values
 ('NURS-BS','Bachelor of Science in Nursing',true),
 ('BUS-BA','Bachelor of Arts in Business',true)
on conflict (code) do nothing;

-- rules (version 1)
insert into persona_rules(version, rule_name, priority, dsl) values
 (1,'Nursing west coast',10,'{
   "if":{"interest_contains":"nursing","zip_in":["9*"]},
   "then":{"program_code":"NURS-BS","score":0.92}
 }'::jsonb),
 (1,'Business default',50,'{
   "if":{"interest_contains":"business"},
   "then":{"program_code":"BUS-BA","score":0.80}
 }'::jsonb)
on conflict do nothing;

-- test lead (store fields in metadata since your table lacks zip/interest)
insert into leads (id, email, phone, metadata)
values (
  '00000000-0000-0000-0000-000000000001',
  'test@example.edu',
  '5551112222',
  jsonb_build_object('zip','94107','interest','nursing')
)
on conflict (id) do nothing;
