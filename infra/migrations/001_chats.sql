-- 001: chat threads (sidebar history). Run once on Neon; schema.sql includes it for fresh installs.
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
