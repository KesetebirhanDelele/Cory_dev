create table programs(
  id uuid primary key default gen_random_uuid(),
  code text unique not null,
  name text not null,
  active boolean default true
);

create table persona_rules(
  id uuid primary key default gen_random_uuid(),
  version int not null,
  rule_name text not null,
  priority int not null,
  dsl jsonb not null,        -- deterministic rules DSL
  created_at timestamptz default now()
);

create table lead_program_scores(
  lead_id uuid references leads(id) on delete cascade,
  program_id uuid references programs(id),
  rules_version int not null,
  fingerprint text not null,          -- deterministic hash of inputs
  score numeric not null,
  source text check (source in ('rules','llm')),
  created_at timestamptz default now(),
  primary key (lead_id, program_id, fingerprint)
);
