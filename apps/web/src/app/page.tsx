"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import QueryBox from "../components/QueryBox";
import ReportStream from "../components/ReportStream";
import ResearchProgress, { type LiveState } from "../components/ResearchProgress";
import SourcesPanel from "../components/SourcesPanel";
import TraceView, { type TraceState } from "../components/TraceView";
import {
  autoTitle,
  createChat,
  deleteChat,
  getChat,
  listChats,
  type ChatMessage,
  type ChatSummary,
} from "../lib/api";
import { streamResearch } from "../lib/sse";

const PRESS = "transition-transform duration-150 ease-out active:scale-[0.96]";
const EASE = { transitionTimingFunction: "cubic-bezier(0.2, 0, 0, 1)" } as const;

const EXAMPLES = [
  "How do small teams choose between pgvector and Qdrant in 2026?",
  "What are the best open-source deep-research agent frameworks in 2026?",
  "Groq LPU vs GPU inference for agentic workloads: tradeoffs?",
];

const emptyTrace = (): TraceState => ({
  route: null,
  plan: [],
  progress: {},
  supported: 0,
  dropped: 0,
  synth: null,
  latencyMs: null,
});

const emptyLive = (): LiveState => ({
  plan: [],
  progress: {},
  supported: 0,
  dropped: 0,
  tokens: 0,
});

type ViewMessage = ChatMessage & { pending?: boolean };

export default function Home() {
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ViewMessage[]>([]);
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<LiveState>(emptyLive);
  const [liveTokens, setLiveTokens] = useState("");
  const [liveTrace, setLiveTrace] = useState<TraceState>(emptyTrace);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [highlightUrl, setHighlightUrl] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const refreshChats = useCallback(async () => {
    try {
      setChats(await listChats());
    } catch {
      /* gateway/API down — thread still works once back */
    }
  }, []);

  useEffect(() => {
    void refreshChats();
  }, [refreshChats]);

  // Follow the stream while running.
  useEffect(() => {
    const el = threadRef.current;
    if (el && running) el.scrollTop = el.scrollHeight;
  }, [running, liveTokens, messages.length]);

  const selectChat = useCallback(
    async (id: string) => {
      abortRef.current?.abort();
      setRunning(false);
      setActiveId(id);
      setSidebarOpen(false);
      setError(null);
      try {
        const chat = await getChat(id);
        setMessages(
          chat.messages.map((m) => ({
            ...m,
            graph: (m.graph as ChatMessage["graph"]) ?? null,
          })),
        );
      } catch {
        setError("Could not load that chat.");
      }
    },
    [],
  );

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    setRunning(false);
    setActiveId(null);
    setMessages([]);
    setLive(emptyLive());
    setLiveTokens("");
    setLiveTrace(emptyTrace());
    setError(null);
    setSidebarOpen(false);
  }, []);

  const removeChat = useCallback(
    async (id: string) => {
      try {
        await deleteChat(id);
      } catch {
        setError("Could not delete that chat.");
        return;
      }
      setChats((prev) => prev.filter((c) => c.id !== id));
      if (activeId === id) newChat();
    },
    [activeId, newChat],
  );

  const ask = useCallback(
    async (q: string) => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setError(null);
      setLive(emptyLive());
      setLiveTokens("");
      setLiveTrace(emptyTrace());

      // Ensure a thread exists (server auto-titles from the query).
      let chatId = activeId;
      if (!chatId) {
        try {
          const created = await createChat(autoTitle(q));
          chatId = created.id;
          setActiveId(chatId);
          setChats((prev) => [
            { id: created.id, title: created.title, updated_at: "", messages: 0 },
            ...prev,
          ]);
        } catch {
          setError("API unreachable — is the stack running (make dev-all)?");
          return;
        }
      }
      const threadId = chatId;
      const userMsg: ViewMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        content: q,
        citations: [],
        graph: null,
        latency_ms: 0,
      };
      setMessages((prev) => [...prev, userMsg]);
      setRunning(true);

      await streamResearch(
        process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3001",
        q,
        {
          onEvent: (e) => {
            switch (e.event) {
              case "plan":
                setLive((l) => ({ ...l, plan: e.data.sub_questions }));
                setLiveTrace((t) => ({ ...t, route: "research", plan: e.data.sub_questions }));
                break;
              case "search_progress":
                setLive((l) => ({
                  ...l,
                  progress: {
                    ...l.progress,
                    [e.data.sub_q_id]: { urls: e.data.urls, claims: e.data.claims },
                  },
                }));
                setLiveTrace((t) => ({
                  ...t,
                  progress: {
                    ...t.progress,
                    [e.data.sub_q_id]: { urls: e.data.urls, claims: e.data.claims },
                  },
                }));
                break;
              case "claim_verified":
                setLive((l) => ({
                  ...l,
                  supported: l.supported + (e.data.verdict === "supported" ? 1 : 0),
                  dropped: l.dropped + (e.data.verdict === "supported" ? 0 : 1),
                }));
                setLiveTrace((t) => ({
                  ...t,
                  supported: t.supported + (e.data.verdict === "supported" ? 1 : 0),
                  dropped: t.dropped + (e.data.verdict === "supported" ? 0 : 1),
                }));
                break;
              case "token":
                setLiveTokens((prev) => prev + e.data.delta);
                setLive((l) => ({ ...l, tokens: l.tokens + e.data.delta.length }));
                break;
              case "done": {
                const d = e.data;
                setRunning(false);
                if (d.reason === "not_research") {
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: d.message_id ?? `local-${Date.now()}`,
                      role: "assistant",
                      content:
                        "_That looks like chitchat, not research — try a factual question._",
                      citations: [],
                      graph: null,
                      latency_ms: 0,
                    },
                  ]);
                  break;
                }
                setMessages((prev) => [
                  ...prev,
                  {
                    id: d.message_id ?? `local-${Date.now()}`,
                    role: "assistant",
                    content: d.report_md || "",
                    citations: d.citations || [],
                    graph: null,
                    latency_ms: d.latency_ms,
                  },
                ]);
                setLiveTokens("");
                setLiveTrace((t) => ({
                  ...t,
                  synth: d.synth
                    ? { coverage: d.synth.coverage, seconds: d.synth.seconds }
                    : null,
                  latencyMs: d.latency_ms,
                }));
                void refreshChats();
                break;
              }
            }
          },
          onError: (err) => {
            setRunning(false);
            setError(err.message);
          },
        },
        { chatId: threadId, signal: ctrl.signal },
      );
    },
    [activeId, refreshChats],
  );

  const contestedOf = useCallback((graph: ChatMessage["graph"]): Set<string> => {
    try {
      const claims =
        (graph as { claims?: { contested?: boolean; sources?: string[] }[] } | null)
          ?.claims ?? [];
      return new Set(
        claims.filter((c) => c.contested).flatMap((c) => c.sources ?? []),
      );
    } catch {
      return new Set<string>();
    }
  }, []);

  const showEmpty = messages.length === 0 && !running;

  return (
    <div className="flex h-dvh overflow-hidden bg-[#09090b] text-zinc-100">
      {/* Backdrop (mobile) */}
      <div
        aria-hidden
        onClick={() => setSidebarOpen(false)}
        className={`fixed inset-0 z-30 bg-black/60 transition-opacity duration-150 ease-out lg:hidden ${
          sidebarOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />
      {/* Sidebar */}
      <aside
        aria-label="Chat history"
        className={`fixed inset-y-0 left-0 z-40 flex w-72 shrink-0 flex-col border-r border-white/[0.07] bg-[#0c0c0e] transition-transform duration-200 ease-out lg:static lg:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={EASE}
      >
        <div className="flex items-center gap-2 p-3">
          <span aria-hidden className="grid h-8 w-8 place-items-center rounded-lg bg-zinc-100 text-sm font-bold text-zinc-900">
            S
          </span>
          <span className="text-sm font-semibold tracking-tight">SignalSift</span>
        </div>
        <div className="px-3 pb-2">
          <button
            type="button"
            onClick={newChat}
            className={`flex w-full items-center justify-center gap-2 rounded-xl bg-zinc-100 px-3 py-2 text-sm font-medium text-zinc-900 transition-[background-color] duration-150 ease-out hover:bg-white focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="h-4 w-4">
              <path strokeLinecap="round" d="M12 5v14M5 12h14" />
            </svg>
            New chat
          </button>
        </div>
        <nav aria-label="Previous chats" className="flex-1 overflow-y-auto px-2 pb-2">
          {chats.length === 0 && (
            <p className="px-2 py-4 text-[13px] text-zinc-600">No chats yet — ask below.</p>
          )}
          <ul className="flex flex-col gap-0.5">
            {chats.map((c) => {
              const active = c.id === activeId;
              return (
                <li key={c.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => void selectChat(c.id)}
                    aria-current={active ? "true" : undefined}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-[13px] transition-[background-color,color] duration-150 ease-out focus-visible:outline-2 focus-visible:outline-white/60 ${
                      active ? "bg-white/[0.08] text-zinc-100" : "text-zinc-400 hover:bg-white/[0.04] hover:text-zinc-200"
                    }`}
                  >
                    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-4 w-4 shrink-0 opacity-60">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M8 10h8M8 14h5M21 12a9 9 0 1 1-4-7.5" />
                    </svg>
                    <span className="min-w-0 flex-1 truncate">{c.title}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${c.title}`}
                    onClick={() => void removeChat(c.id)}
                    className="absolute top-1/2 right-1.5 hidden -translate-y-1/2 rounded-md p-1 text-zinc-500 transition-[opacity,background-color,color] duration-150 ease-out group-hover:block hover:bg-white/10 hover:text-zinc-200 focus-visible:block focus-visible:outline-2 focus-visible:outline-white/60"
                  >
                    <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-3.5 w-3.5">
                      <path strokeLinecap="round" d="M6 6l12 12M18 6 6 18" />
                    </svg>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        <p className="border-t border-white/[0.06] px-4 py-3 text-[11px] leading-4 text-zinc-600">
          Groq swarm · every claim cited
        </p>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-white/[0.06] px-3 py-2.5 lg:hidden">
          <button
            type="button"
            aria-label="Open chat history"
            onClick={() => setSidebarOpen(true)}
            className={`rounded-lg p-2 text-zinc-300 transition-[background-color] duration-150 hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
          >
            <svg aria-hidden viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="h-5 w-5">
              <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>
          <span className="text-sm font-semibold">SignalSift</span>
        </header>

        <div ref={threadRef} className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 overflow-y-auto px-4 py-6 sm:px-6">
          {showEmpty && (
            <div className="flex flex-1 flex-col items-center justify-center text-center">
              <p className="stagger mb-2 text-xs font-semibold tracking-[0.2em] text-zinc-500 uppercase" style={{ animationDelay: "0ms" }}>
                Groq research swarm
              </p>
              <h1 className="stagger text-3xl font-semibold tracking-tight sm:text-4xl" style={{ animationDelay: "100ms" }}>
                What should we research?
              </h1>
              <div className="stagger mt-5 flex max-w-md flex-wrap justify-center gap-2" style={{ animationDelay: "200ms" }}>
                {EXAMPLES.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    onClick={() => void ask(ex)}
                    className={`rounded-full bg-white/[0.04] px-3.5 py-1.5 text-[13px] text-zinc-400 outline-1 outline-white/10 transition-[background-color,color] duration-150 ease-out hover:bg-white/[0.08] hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
                  >
                    {ex.length > 56 ? `${ex.slice(0, 56)}…` : ex}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m) =>
            m.role === "user" ? (
              <div key={m.id} className="flex justify-end">
                <p className="max-w-[85%] rounded-2xl rounded-br-md bg-white/[0.08] px-4 py-2.5 text-[15px] leading-7 whitespace-pre-wrap">
                  {m.content}
                </p>
              </div>
            ) : (
              <div key={m.id} className="min-w-0">
                <ReportStream
                  markdown={m.content}
                  streaming={false}
                  sources={m.citations}
                  onHoverSource={setHighlightUrl}
                />
                {m.citations.length > 0 && (
                  <details className="group mt-4">
                    <summary className="cursor-pointer text-[13px] font-medium text-zinc-400 transition-colors duration-150 ease-out hover:text-zinc-200">
                      {m.citations.length} sources
                      {typeof m.latency_ms === "number" && m.latency_ms > 0 && (
                        <span className="ml-2 text-zinc-600 tabular-nums">
                          {(m.latency_ms / 1000).toFixed(1)}s
                        </span>
                      )}
                    </summary>
                    <div className="mt-3">
                      <SourcesPanel
                        sources={m.citations}
                        contestedUrls={contestedOf(m.graph)}
                        highlightUrl={highlightUrl}
                      />
                    </div>
                  </details>
                )}
              </div>
            ),
          )}

          {running && (
            <div className="min-w-0" aria-live="polite">
              <ResearchProgress live={live} running={running} />
              {liveTokens ? (
                <ReportStream
                  markdown={liveTokens}
                  streaming
                  sources={[]}
                  onHoverSource={setHighlightUrl}
                />
              ) : (
                <p className="text-sm text-zinc-500">Planning searches…</p>
              )}
              <details className="mt-4">
                <summary className="cursor-pointer text-[13px] font-medium text-zinc-500 transition-colors duration-150 ease-out hover:text-zinc-300">
                  Run trace
                </summary>
                <div className="mt-3 rounded-xl bg-white/[0.02] p-4 outline-1 outline-white/[0.07]">
                  <TraceView trace={liveTrace} running={running} />
                </div>
              </details>
            </div>
          )}

          {error && (
            <div className="rounded-xl bg-red-500/[0.08] p-4 text-sm text-red-300 outline-1 outline-red-400/20">
              {error}
            </div>
          )}
        </div>

        <div className="mx-auto w-full max-w-3xl px-4 pt-2 pb-4 sm:px-6 sm:pb-6">
          <QueryBox loading={running} onAsk={(q) => void ask(q)} />
          <p className="mt-2 text-center text-[11px] text-zinc-600">
            Verified claims only — dropped statements never reach the report.
          </p>
        </div>
      </div>
    </div>
  );
}
