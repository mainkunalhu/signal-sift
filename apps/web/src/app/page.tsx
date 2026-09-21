"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import QueryBox from "../components/QueryBox";
import ReportStream from "../components/ReportStream";
import SourcesPanel from "../components/SourcesPanel";
import TraceView, { type TraceState } from "../components/TraceView";
import type { Citation, CitationGraph } from "../lib/events";
import { streamResearch } from "../lib/sse";

const GATEWAY = process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:3001";
const PRESS = "transition-transform duration-150 ease-out active:scale-[0.96]";

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

export default function Home() {
  const [phase, setPhase] = useState<"idle" | "running" | "done" | "error">("idle");
  const [query, setQuery] = useState("");
  const [tokens, setTokens] = useState("");
  const [report, setReport] = useState("");
  const [citations, setCitations] = useState<Citation[]>([]);
  const [graph, setGraph] = useState<CitationGraph | null>(null);
  const [trace, setTrace] = useState<TraceState>(emptyTrace);
  const [error, setError] = useState<string | null>(null);
  const [highlightUrl, setHighlightUrl] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const ask = useCallback((q: string) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setQuery(q);
    setTokens("");
    setReport("");
    setCitations([]);
    setGraph(null);
    setTrace(emptyTrace());
    setError(null);
    setPhase("running");

    void streamResearch(
      GATEWAY,
      q,
      {
        onEvent: (e) => {
          switch (e.event) {
            case "plan":
              setTrace((t) => ({ ...t, route: "research", plan: e.data.sub_questions }));
              break;
            case "search_progress":
              setTrace((t) => ({
                ...t,
                progress: {
                  ...t.progress,
                  [e.data.sub_q_id]: { urls: e.data.urls, claims: e.data.claims },
                },
              }));
              break;
            case "claim_verified":
              setTrace((t) => ({
                ...t,
                supported: t.supported + (e.data.verdict === "supported" ? 1 : 0),
                dropped: t.dropped + (e.data.verdict === "supported" ? 0 : 1),
              }));
              break;
            case "token":
              setTokens((prev) => prev + e.data.delta);
              break;
            case "done": {
              const d = e.data as Extract<
                Parameters<Parameters<typeof streamResearch>[2]["onEvent"]>[0],
                { event: "done" }
              >["data"];
              if ("reason" in d && (d as { reason?: string }).reason === "not_research") {
                setError("That looks like chitchat, not research — try a factual question.");
                setPhase("error");
                break;
              }
              setReport(d.report_md || "");
              setCitations(d.citations || []);
              setGraph(d.citation_graph || null);
              setTrace((t) => ({
                ...t,
                synth: d.synth ? { coverage: d.synth.coverage, seconds: d.synth.seconds } : null,
                latencyMs: d.latency_ms,
              }));
              setPhase("done");
              break;
            }
          }
        },
        onError: (err) => {
          setError(err.message);
          setPhase("error");
        },
      },
      { signal: ctrl.signal },
    );
  }, []);

  const contestedUrls = useMemo(
    () =>
      new Set(
        (graph?.claims ?? []).filter((c) => c.contested).flatMap((c) => c.sources),
      ),
    [graph],
  );

  const running = phase === "running";
  const showResults = phase !== "idle";
  const markdown = phase === "done" && report ? report : tokens;

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-6xl flex-col px-4 pb-16 sm:px-6">
      {/* Hero: staggered entrance (infrequent, runs once). */}
      <header className="mx-auto flex w-full max-w-2xl flex-col items-center pt-14 text-center sm:pt-20">
        <p className="stagger mb-3 text-xs font-semibold tracking-[0.2em] text-zinc-500 uppercase" style={{ animationDelay: "0ms" }}>
          Groq research swarm
        </p>
        <h1 className="stagger text-4xl font-semibold tracking-tight text-zinc-50 sm:text-5xl" style={{ animationDelay: "100ms" }}>
          SignalSift
        </h1>
        <p className="stagger mt-3 max-w-md text-[15px] leading-6 text-zinc-400" style={{ animationDelay: "200ms" }}>
          One hard question. Parallel agents. Every claim cited.
        </p>
        <div className="stagger mt-6 w-full" style={{ animationDelay: "300ms" }}>
          <QueryBox loading={running} onAsk={ask} />
        </div>
        {phase === "idle" && (
          <div className="stagger mt-4 flex flex-wrap justify-center gap-2" style={{ animationDelay: "400ms" }}>
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => ask(ex)}
                className={`rounded-full bg-white/[0.04] px-3.5 py-1.5 text-[13px] text-zinc-400 outline-1 outline-white/10 transition-[background-color,color,outline-color] duration-150 ease-out hover:bg-white/[0.08] hover:text-zinc-200 focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
              >
                {ex.length > 52 ? `${ex.slice(0, 52)}…` : ex}
              </button>
            ))}
          </div>
        )}
      </header>

      {showResults && (
        <main className="mt-10 flex w-full flex-col gap-8 lg:grid lg:grid-cols-[minmax(0,1fr)_320px] lg:gap-10">
          <div className="flex min-w-0 flex-col gap-6">
            <div className="rounded-2xl bg-white/[0.02] p-5 outline-1 outline-white/[0.07] sm:p-6">
              <h2 className="mb-1 line-clamp-2 text-lg font-semibold text-zinc-100">{query}</h2>
              <p className="mb-4 text-xs text-zinc-500 tabular-nums" aria-live="polite">
                {running
                  ? "Researching across parallel agents…"
                  : error
                    ? "Research stopped."
                    : `${citations.length} sources · verified report below`}
              </p>
              {error ? (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-sm text-red-300">{error}</p>
                  <button
                    type="button"
                    onClick={() => query && ask(query)}
                    className={`rounded-xl bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 transition-[background-color] duration-150 ease-out hover:bg-white focus-visible:outline-2 focus-visible:outline-white/60 ${PRESS}`}
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <ReportStream
                  markdown={markdown || (running ? "" : "_No report returned._")}
                  streaming={running}
                  sources={citations}
                  onHoverSource={setHighlightUrl}
                />
              )}
            </div>
            <div className="rounded-2xl bg-white/[0.02] p-5 outline-1 outline-white/[0.07] lg:hidden">
              <SourcesPanel sources={citations} contestedUrls={contestedUrls} highlightUrl={highlightUrl} />
            </div>
          </div>

          <aside className="flex min-w-0 flex-col gap-8">
            <div className="rounded-2xl bg-white/[0.02] p-5 outline-1 outline-white/[0.07]">
              <TraceView trace={trace} running={running} />
            </div>
            <div className="sticky top-6 hidden rounded-2xl bg-white/[0.02] p-5 outline-1 outline-white/[0.07] lg:block">
              <SourcesPanel sources={citations} contestedUrls={contestedUrls} highlightUrl={highlightUrl} />
            </div>
          </aside>
        </main>
      )}

      <footer className="mt-auto pt-12 text-center text-xs text-zinc-600">
        SignalSift · Groq swarm · faithfulness over fluency
      </footer>
    </div>
  );
}
