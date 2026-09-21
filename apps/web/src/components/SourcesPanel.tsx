"use client";

import { memo, useState } from "react";
import type { Citation } from "../lib/events";

function domainOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function Favicon({ domain }: { domain: string }) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;
  return (
    // 1px pure-white low-opacity outline per image-outline rule (dark UI).
    <img
      src={`https://www.google.com/s2/favicons?domain=${domain}&sz=64`}
      alt=""
      aria-hidden
      loading="lazy"
      width={16}
      height={16}
      onError={() => setHidden(true)}
      className="h-4 w-4 shrink-0 rounded-[4px] outline-1 outline-white/10"
    />
  );
}

function SourcesPanel({
  sources,
  contestedUrls,
  highlightUrl,
}: {
  sources: Citation[];
  contestedUrls: Set<string>;
  highlightUrl: string | null;
}) {
  if (sources.length === 0) return null;
  return (
    <section aria-label="Sources" className="min-w-0">
      <h2 className="mb-3 text-xs font-semibold tracking-widest text-zinc-500 uppercase">
        Sources · {sources.length}
      </h2>
      <ol className="flex flex-col gap-2">
        {sources.map((src, i) => {
          const active = highlightUrl === src.url;
          return (
            <li key={`${src.url}-${i}`}>
              <a
                href={src.url}
                target="_blank"
                rel="noopener noreferrer"
                className={`group flex items-start gap-3 rounded-xl bg-white/[0.03] p-2.5 outline-1 transition-[background-color,outline-color] duration-150 ease-out hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-white/60 active:scale-[0.96] ${
                  active ? "outline-white/30" : "outline-white/[0.07]"
                }`}
              >
                <span
                  aria-hidden
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-white/[0.07] text-[11px] font-semibold text-zinc-300 tabular-nums"
                >
                  {i + 1}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] leading-5 font-medium text-zinc-200">
                    {src.title || domainOf(src.url)}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1.5 text-xs text-zinc-500">
                    <Favicon domain={domainOf(src.url)} />
                    <span className="truncate">{domainOf(src.url)}</span>
                    {contestedUrls.has(src.url) && (
                      <span className="shrink-0 rounded-full bg-amber-400/10 px-1.5 py-px text-[10px] font-medium text-amber-300">
                        contested
                      </span>
                    )}
                  </span>
                </span>
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export default memo(SourcesPanel);
