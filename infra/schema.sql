-- SignalSift schema (Neon / Supabase, Postgres + pgvector)
create extension if not exists vector;
create extension if not exists pg_trgm;

create table if not exists queries (
  id uuid primary key default gen_random_uuid(),
  text text not null,
  plan_json jsonb default '{}',
  created_at timestamptz default now()
);

create table if not exists documents (
  id uuid primary key default gen_random_uuid(),
  query_id uuid references queries(id) on delete cascade,
  url text not null,
  title text,
  content_hash text unique,
  embedding vector(384),
  created_at timestamptz default now()
);

create table if not exists claims (
  id uuid primary key default gen_random_uuid(),
  doc_id uuid references documents(id) on delete cascade,
  text text not null,
  embedding vector(384),
  verdict text default 'pending',
  citations jsonb default '[]',
  created_at timestamptz default now()
);

create index if not exists idx_documents_embedding on documents using ivfflat (embedding vector_cosine_ops);
create index if not exists idx_claims_embedding on claims using ivfflat (embedding vector_cosine_ops);

-- chat threads (sidebar history)
create table if not exists chats (
  id uuid primary key default gen_random_uuid(),
  title text not null default 'New research',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists messages (
  id uuid primary key default gen_random_uuid(),
  chat_id uuid not null references chats(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null default '',
  citations jsonb default '[]',
  graph jsonb default '{}',
  latency_ms int default 0,
  created_at timestamptz default now()
);

create index if not exists idx_messages_chat on messages(chat_id, created_at);
