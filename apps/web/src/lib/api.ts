"use client";

/** REST helpers for chat threads (through the gateway). */

import type { CitationGraph } from "./events";

const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3001";

export interface ChatSummary {
  id: string;
  title: string;
  updated_at: string;
  messages: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: { url: string; title: string }[];
  graph: CitationGraph | null;
  latency_ms: number;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${GATEWAY.replace(/\/$/, "")}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`chats API: HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export const listChats = () =>
  json<{ chats: ChatSummary[] }>("/api/chats").then((r) => r.chats);

export const createChat = (title: string) =>
  json<{ id: string; title: string }>("/api/chats", {
    method: "POST",
    body: JSON.stringify({ title }),
  });

export const getChat = (id: string) =>
  json<{ id: string; title: string; messages: ChatMessage[] }>(`/api/chats/${id}`);

export const deleteChat = (id: string) =>
  json<{ ok: boolean }>(`/api/chats/${id}`, { method: "DELETE" });

export function autoTitle(query: string): string {
  const t = query.split(/\s+/).join(" ").trim();
  return t.length > 60 ? `${t.slice(0, 57)}…` : t || "New research";
}
