-- Create base tables if not exist
create extension if not exists vector;

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    title text,
    content text,
    metadata jsonb
);

create table if not exists embeddings (
    id uuid primary key default gen_random_uuid(),
    doc_id uuid references documents(id) on delete cascade,
    content text,
    embedding vector(1536)
);

-- pgvector retrieval RPC
create or replace function match_documents(
    query_embedding vector(1536),
    similarity_threshold float,
    match_count int
)
returns table (
    id uuid,
    content text,
    similarity float
)
language plpgsql
as $$
begin
    return query
    select
        e.doc_id,
        e.content,
        1 - (e.embedding <=> query_embedding) as similarity
    from embeddings e
    where 1 - (e.embedding <=> query_embedding) > similarity_threshold
    order by similarity desc
    limit match_count;
end;
$$;
