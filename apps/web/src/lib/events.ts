/** Local copy of the SSE/domain contract.
 *  Canonical source: packages/shared/src/types.ts (kept in sync manually;
 *  no workspace linker in this monorepo yet).
 */

export interface Citation {
  url: string;
  title: string;
}

export interface CitedClaim {
  text: string;
  quotes: string[];
  sources: string[];
  contested: boolean;
}

export interface CitationGraph {
  claims: CitedClaim[];
  docs: Citation[];
  stats: {
    claims_total: number;
    claims_supported: number;
    claims_dropped: number;
    cited_claims: number;
    contested: number;
  };
}

export interface SubQuestion {
  id: string;
  question: string;
  search_queries: string[];
  priority: number;
}

export type SseEvent =
  | { event: "plan"; data: { sub_questions: SubQuestion[] } }
  | {
      event: "search_progress";
      data: { sub_q_id: string; status: "done"; urls: string[]; claims: number };
    }
  | {
      event: "claim_verified";
      data: {
        claim_id: string;
        verdict: "supported" | "unsupported";
        url: string;
        attempts: number;
      };
    }
  | { event: "token"; data: { delta: string } }
  | {
      event: "done";
      data: {
        query_id: string | null;
        chat_id: string | null;
        message_id: string | null;
        route?: { route: string };
        reason?: string;
        report_md: string;
        citations: Citation[];
        citation_graph: CitationGraph;
        synth: {
          repaired: boolean;
          coverage: number;
          claims_used: number;
          docs_used: number;
          tokens_est: number;
          seconds: number;
        } | null;
        latency_ms: number;
      };
    };
