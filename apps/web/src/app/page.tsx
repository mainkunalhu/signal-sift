"use client";

import { Plus, Sparkles } from "lucide-react";
import Image from "next/image";
import { useCallback, useEffect, useRef, useState } from "react";
import QueryBox from "../components/QueryBox";
import ReportStream from "../components/ReportStream";
import ResearchProgress, { type LiveState } from "../components/ResearchProgress";
import SourcesPanel from "../components/SourcesPanel";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { autoTitle, createChat, type ChatMessage } from "../lib/api";
import { streamResearch } from "../lib/sse";

const PRESS = "transition-transform duration-150 ease-out active:scale-[0.96]";

const EXAMPLES = [
  "How do small teams choose between pgvector and Qdrant in 2026?",
  "What are the best open-source deep-research agent frameworks in 2026?",
  "Groq LPU vs GPU inference for agentic workloads: tradeoffs?",
];

const emptyLive = (): LiveState => ({
  plan: [],
  progress: {},
  supported: 0,
  dropped: 0,
  tokens: 0,
});

function contestedOf(graph: ChatMessage["graph"]): Set<string> {
  try {
    const claims =
      (graph as { claims?: { contested?: boolean; sources?: string[] }[] } | null)
        ?.claims ?? [];
    return new Set(claims.filter((c) => c.contested).flatMap((c) => c.sources ?? []));
  } catch {
    return new Set<string>();
  }
}

export default function Home() {
  const [chatId, setChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<LiveState>(emptyLive);
  const [liveTokens, setLiveTokens] = useState("");
  const [tokensActive, setTokensActive] = useState(false);
  const [stalled, setStalled] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [highlightUrl, setHighlightUrl] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const tokenTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastEventAt = useRef<number>(0);
  const stallTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);

  const pokeTokensActive = useCallback(() => {
    setTokensActive(true);
    if (tokenTimer.current) clearTimeout(tokenTimer.current);
    // Caret follows real token flow: stalls longer than this hide it,
    // so a finished-or-cut stream never blinks forever.
    tokenTimer.current = setTimeout(() => setTokensActive(false), 2500);
  }, []);

  const stopTokensActive = useCallback(() => {
    if (tokenTimer.current) clearTimeout(tokenTimer.current);
    setTokensActive(false);
  }, []);

  const stopStallWatch = useCallback(() => {
    if (stallTimer.current) clearInterval(stallTimer.current);
    stallTimer.current = null;
    setStalled(false);
  }, []);

  const startStallWatch = useCallback(() => {
    lastEventAt.current = Date.now();
    setStalled(false);
    if (stallTimer.current) clearInterval(stallTimer.current);
    // Silence longer than this means free-tier queues, not progress.
    stallTimer.current = setInterval(() => {
      if (Date.now() - lastEventAt.current > 25000) setStalled(true);
    }, 5000);
  }, []);

  // Follow the stream while running.
  useEffect(() => {
    const el = threadRef.current;
    if (el && running) el.scrollTop = el.scrollHeight;
  }, [running, liveTokens, messages.length]);

  // Never leak the watchdog.
  useEffect(
    () => () => {
      if (stallTimer.current) clearInterval(stallTimer.current);
      if (tokenTimer.current) clearTimeout(tokenTimer.current);
    },
    [],
  );

  const newChat = useCallback(() => {
    abortRef.current?.abort();
    stopTokensActive();
    setRunning(false);
    setChatId(null);
    setMessages([]);
    setLive(emptyLive());
    setLiveTokens("");
    setError(null);
    stopStallWatch();
  }, [stopTokensActive, stopStallWatch]);

  const ask = useCallback(
    async (q: string) => {
      // Instant feedback first: user message + spinner render immediately,
      // so a slow network can never look "stuck".
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      setError(null);
      setLive(emptyLive());
      setLiveTokens("");
      stopTokensActive();
      startStallWatch();
      setRunning(true);
      setMessages((prev) => [
        ...prev,
        {
          id: `local-${Date.now()}`,
          role: "user",
          content: q,
          citations: [],
          graph: null,
          latency_ms: 0,
        },
      ]);

      // Thread for follow-ups (server auto-titles from the first query).
      let threadId = chatId;
      if (!threadId) {
        try {
          threadId = (await createChat(autoTitle(q))).id;
          setChatId(threadId);
        } catch {
          setRunning(false);
          setError("API unreachable — is the stack running (make dev-all)?");
          return;
        }
      }

      await streamResearch(
        process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3001",
        q,
        {
          onEvent: (e) => {
            lastEventAt.current = Date.now();
            setStalled(false);
            switch (e.event) {
              case "plan":
                setLive((l) => ({ ...l, plan: e.data.sub_questions }));
                break;
              case "search_progress": {
                setLive((l) => ({
                  ...l,
                  progress: {
                    ...l.progress,
                    [e.data.sub_q_id]: { urls: e.data.urls, claims: e.data.claims },
                  },
                }));
                break;
              }
              case "claim_verified":
                setLive((l) => ({
                  ...l,
                  supported: l.supported + (e.data.verdict === "supported" ? 1 : 0),
                  dropped: l.dropped + (e.data.verdict === "supported" ? 0 : 1),
                }));
                break;
              case "token":
                setLiveTokens((prev) => prev + e.data.delta);
                setLive((l) => ({ ...l, tokens: l.tokens + e.data.delta.length }));
                pokeTokensActive();
                break;
              case "done": {
                const d = e.data;
                setRunning(false);
                stopTokensActive();
                stopStallWatch();
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
                    graph: d.citation_graph ?? null,
                    latency_ms: d.latency_ms,
                  },
                ]);
                setLiveTokens("");
                break;
              }
            }
          },
          onError: (err) => {
            setRunning(false);
            stopTokensActive();
            stopStallWatch();
            setError(err.message);
          },
        },
        { chatId: threadId, signal: ctrl.signal },
      );
    },
    [chatId, pokeTokensActive, stopTokensActive, startStallWatch, stopStallWatch],
  );

  const showEmpty = messages.length === 0 && !running && !error;
  // Staged live view: research activity first, streaming report after.
  const tokensStarted = liveTokens.length > 0;

  return (
    <div
      className="mx-auto flex h-screen w-full max-w-3xl flex-col overflow-hidden px-4 sm:px-6"
      style={{ height: "100dvh" }}
    >
      <header className="flex items-center gap-2 py-3">
        <Image
          src="/logo.png"
          alt="SignalSift logo"
          width={28}
          height={28}
          priority
          className="h-7 w-7 rounded-lg outline-1 outline-white/10"
        />
        <span className="text-sm font-semibold tracking-tight">SignalSift</span>
        <span className="ml-auto" />
        <Button variant="ghost" size="sm" onClick={newChat} aria-label="Start a new chat">
          <Plus aria-hidden strokeWidth={2} className="h-4 w-4" />
          New chat
        </Button>
      </header>

      {showEmpty ? (
        <main className="flex flex-1 flex-col items-center justify-center pb-16 text-center">
          <p
            className="stagger mb-3 flex items-center gap-1.5 text-xs font-semibold tracking-[0.2em] text-zinc-500 uppercase"
            style={{ animationDelay: "0ms" }}
          >
            <Sparkles aria-hidden strokeWidth={2} className="h-3.5 w-3.5" />
            Groq research swarm
          </p>
          <h1
            className="stagger text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl"
            style={{ animationDelay: "100ms" }}
          >
            What should we research?
          </h1>
          <p
            className="stagger mt-3 max-w-md text-[15px] leading-6 text-zinc-400"
            style={{ animationDelay: "200ms" }}
          >
            One hard question. Parallel agents. Every claim cited.
          </p>
          <div className="stagger mt-7 w-full" style={{ animationDelay: "300ms" }}>
            <QueryBox loading={running} onAsk={(q) => void ask(q)} autoFocus />
          </div>
          <div
            className="stagger mt-4 grid w-full gap-2 text-left sm:grid-cols-3"
            style={{ animationDelay: "400ms" }}
          >
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => void ask(ex)}
                className={`rounded-xl bg-white/[0.03] p-3 text-[13px] leading-5 text-zinc-400 outline-1 outline-white/[0.08] transition-[background-color,color,outline-color] duration-150 ease-out hover:bg-white/[0.06] hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
              >
                {ex}
              </button>
            ))}
          </div>
        </main>
      ) : (
        <>
          <div
            ref={threadRef}
            className="no-scrollbar flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto py-6"
            aria-live="polite"
          >
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
                {stalled && (
                  <p className="mb-3 rounded-xl bg-amber-400/[0.07] p-3 text-[13px] leading-5 text-amber-200/90 outline-1 outline-amber-400/20">
                    Still working — free-tier queues can stall for a bit. It will
                    resume on its own; only retry if this persists for minutes.
                  </p>
                )}
                {tokensStarted ? (
                  <>
                    <p className="mb-3 flex items-center gap-2 text-[13px] text-zinc-400">
                      <Badge variant="sky">writing report</Badge>
                      <span className="tabular-nums text-zinc-500">
                        {Object.values(live.progress).reduce((a, p) => a + p.urls.length, 0)}{" "}
                        sources · {live.supported} claims kept
                      </span>
                    </p>
                    <ReportStream
                      markdown={liveTokens}
                      streaming={tokensActive}
                      sources={[]}
                      onHoverSource={setHighlightUrl}
                    />
                  </>
                ) : (
                  <>
                    <ResearchProgress live={live} running={running} />
                    <p className="text-sm text-zinc-500">Gathering evidence…</p>
                  </>
                )}
              </div>
            )}

            {error && !running && (
              <div className="flex flex-col items-start gap-3 rounded-xl bg-red-500/[0.08] p-4 text-sm text-red-300 outline-1 outline-red-400/20">
                <p>{error}</p>
                <Button variant="secondary" size="sm" onClick={() => setError(null)}>
                  Dismiss
                </Button>
              </div>
            )}
          </div>

          <div className="pt-2 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <QueryBox loading={running} onAsk={(q) => void ask(q)} />
            <p className="mt-2 text-center text-[11px] text-zinc-600">
              Verified claims only — dropped statements never reach the report.
            </p>
          </div>
        </>
      )}

      <footer className="pb-4 text-center text-[11px] text-zinc-700">
        SignalSift · Groq swarm · faithfulness over fluency
      </footer>
    </div>
  );
}
