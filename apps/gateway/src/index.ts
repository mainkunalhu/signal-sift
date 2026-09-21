import { Hono } from "hono";
import { cors } from "hono/cors";

const API_URL = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PORT = Number(process.env.GATEWAY_PORT ?? process.env.PORT ?? 3001);

// 10 req/min per IP sliding window (demo-grade; use Redis in prod).
const WINDOW_MS = 60_000;
const LIMIT = 10;
const hits = new Map<string, number[]>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const window = (hits.get(ip) ?? []).filter((t) => now - t < WINDOW_MS);
  window.push(now);
  hits.set(ip, window);
  if (hits.size > 10_000) hits.clear();
  return window.length > LIMIT;
}

const app = new Hono();

app.use("/*", cors({ origin: "*", allowMethods: ["GET", "POST", "OPTIONS"] }));

app.get("/health", (c) => c.json({ ok: true, service: "signalsift-gateway" }));

app.all("/api/*", async (c) => {
  const ip =
    c.req.header("x-forwarded-for")?.split(",")[0]?.trim() ??
    c.req.header("x-real-ip") ??
    "unknown";
  if (rateLimited(ip)) {
    return c.json({ error: "rate limited: 10 requests per minute" }, 429);
  }
  const target = `${API_URL}${new URL(c.req.url).pathname}${new URL(c.req.url).search}`;
  const headers = new Headers(c.req.raw.headers);
  headers.delete("host");
  const upstream = await fetch(target, {
    method: c.req.method,
    headers,
    body: ["GET", "HEAD"].includes(c.req.method) ? undefined : c.req.raw.body,
    // @ts-expect-error Bun/undici streaming body
    duplex: "half",
  });
  const out = new Headers(upstream.headers);
  out.set("access-control-allow-origin", "*");
  return new Response(upstream.body, { status: upstream.status, headers: out });
});

export default {
  port: PORT,
  fetch: app.fetch,
  // SSE runs go quiet for 10s+ (120b prefill, NLI batches). Bun's 10s
  // default would sever curl/browser mid-report.
  idleTimeout: 180,
};
