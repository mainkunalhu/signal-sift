"use client";

import { memo, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation } from "../lib/events";

const CITE_RE = /\[(\d+)\]/g;

/** Inline [n] citation chip: number always visible (static cue), hover shows
 *  source, click opens it. Hover also highlights the matching sidebar row.
 */
function Cite({
  n,
  sources,
  onHover,
}: {
  n: number;
  sources: Citation[];
  onHover: (url: string | null) => void;
}) {
  const src = sources[n - 1];
  if (!src) return <span className="text-zinc-500">[{n}]</span>;
  return (
    <a
      href={src.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`${src.title}\n${src.url}`}
      aria-label={`Source ${n}: ${src.title}`}
      onMouseEnter={() => onHover(src.url)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(src.url)}
      onBlur={() => onHover(null)}
      className="mx-0.5 inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-white/[0.07] px-1 align-super text-[11px] font-medium text-zinc-200 tabular-nums outline-1 outline-white/10 transition-[background-color,outline-color] duration-150 ease-out hover:bg-white/[0.14] hover:outline-white/25 focus-visible:outline-2 focus-visible:outline-white/60 active:scale-[0.96]"
    >
      {n}
    </a>
  );
}

/** Split paragraph text nodes on [n] markers; render chips in place. */
function CitedParagraph({
  sources,
  onHoverSource,
  ...props
}: React.HTMLAttributes<HTMLParagraphElement> & {
  sources: Citation[];
  onHoverSource: (url: string | null) => void;
}) {
  const kids = useMemo(() => {
    const out: React.ReactNode[] = [];
    const pushText = (text: string, keyBase: string) => {
      let last = 0;
      let m: RegExpExecArray | null;
      CITE_RE.lastIndex = 0;
      let k = 0;
      while ((m = CITE_RE.exec(text)) !== null) {
        if (m.index > last) out.push(text.slice(last, m.index));
        out.push(
          <Cite
            key={`${keyBase}-${k++}`}
            n={Number(m[1])}
            sources={sources}
            onHover={onHoverSource}
          />,
        );
        last = m.index + m[0].length;
      }
      if (last < text.length) out.push(text.slice(last));
    };
    const walk = (node: React.ReactNode, keyBase: string): void => {
      if (typeof node === "string") pushText(node, keyBase);
      else out.push(node);
    };
    const children = props.children as React.ReactNode;
    if (Array.isArray(children)) children.forEach((c, i) => walk(c, String(i)));
    else walk(children, "0");
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.children, sources, onHoverSource]);

  return <p {...props}>{kids}</p>;
}

function ReportStream({
  markdown,
  streaming,
  sources,
  onHoverSource,
}: {
  markdown: string;
  streaming: boolean;
  sources: Citation[];
  onHoverSource: (url: string | null) => void;
}) {
  return (
    <article className="min-w-0">
      <div className="prose-signal">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            p: (props) => (
              <CitedParagraph sources={sources} onHoverSource={onHoverSource} {...props} />
            ),
          }}
        >
          {markdown}
        </ReactMarkdown>
      </div>
      {streaming && (
        <span
          aria-hidden
          className="mt-1 inline-block h-4 w-2 animate-pulse rounded-[2px] bg-zinc-300"
        />
      )}
    </article>
  );
}

export default memo(ReportStream);
