-- 1) Enable pgvector (adds the `vector` type)
create extension if not exists vector;

-- 2) Enable gen_random_uuid() default (or use uuid-ossp if you prefer uuid_generate_v4)
create extension if not exists pgcrypto;
-- alternatively: create extension if not exists "uuid-ossp";

create table docs(id uuid primary key default gen_random_uuid(), title text, source text, org_id uuid);
create table doc_chunks(
  id bigserial primary key,
  doc_id uuid references docs(id) on delete cascade,
  content text not null,
  embedding vector(1536),
  metadata jsonb,
  org_id uuid
);

-- L2 distance (use cosine_ops if you normalize to unit length)
create index if not exists doc_chunks_embedding_ivfflat
  on doc_chunks using ivfflat (embedding vector_l2_ops) with (lists = 100);

-- and gather stats
analyze doc_chunks;
