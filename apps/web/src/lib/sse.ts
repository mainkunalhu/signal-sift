"use client";

/** Minimal SSE-over-POST client: parses frames, dispatches typed events.
 *  One automatic retry on network failure before the first byte; after that
 *  errors surface to the UI (retry button), never hidden loops.
 */
import type { SseEvent } from "./events";

export interface StreamOptions {
  maxSubquestions?: number;
  signal?: AbortSignal;
}

export async function streamResearch(
  baseUrl: string,
  query: string,
  handlers: {
    onEvent: (e: SseEvent) => void;
    onError: (err: Error) => void;
  },
  opts: StreamOptions = {},
): Promise<void> {
  const run = async () => {
    const res = await fetch(`${baseUrl.replace(/\/$/, "")}/api/research`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        query,
        max_subquestions: opts.maxSubquestions ?? 5,
      }),
      signal: opts.signal,
    });
    if (!res.ok) throw new Error(`research failed: HTTP ${res.status}`);
    if (!res.body) throw new Error("empty response body");

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? "";
      for (const frame of frames) {
        const event = parseFrame(frame);
        if (event) handlers.onEvent(event);
      }
    }
  };

  try {
    await run();
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    // Single retry for pre-flight network failures only.
    try {
      await new Promise((r) => setTimeout(r, 800));
      if (opts.signal?.aborted) return;
      await run();
    } catch (err2) {
      if ((err2 as Error).name !== "AbortError") handlers.onError(err2 as Error);
    }
  }
}

function parseFrame(frame: string): SseEvent | null {
  let event = "";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    else if (line.startsWith(":")) continue; // ping/comment
  }
  if (!event || dataLines.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataLines.join("\n")) } as SseEvent;
  } catch {
    return null;
  }
}
