#!/usr/bin/env node
/**
 * Engram MCP Server
 *
 * Exposes cognitive memory tools to any MCP-compatible client:
 * Claude Code, Cursor, Zed, Claude Desktop, etc.
 *
 * Usage:
 *   ENGRAM_SERVICE_URL=http://127.0.0.1:18080 node dist/index.js
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const SERVICE_URL = process.env.ENGRAM_SERVICE_URL ?? "http://127.0.0.1:18080";

async function post(path: string, body: unknown): Promise<unknown> {
  const resp = await fetch(`${SERVICE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`Engram service error ${resp.status}: ${text}`);
  }
  return resp.json();
}

async function get(path: string): Promise<unknown> {
  const resp = await fetch(`${SERVICE_URL}${path}`);
  if (!resp.ok) throw new Error(`Engram service error ${resp.status}`);
  return resp.json();
}

const server = new McpServer({
  name: "engram",
  version: "0.1.0",
});

// ── Tool: capture ─────────────────────────────────────────────────────────────

server.tool(
  "cognitive_capture_thought",
  "Capture a user's thought, reflection, idea, observation, or decision into the Engram " +
  "cognitive graph as a new entry. " +
  "Use ONLY when the user's intent is to RECORD / SAVE / LOG something — i.e. they want it " +
  "preserved for future analysis. Strong signals in the user's message: 记录 / 保存 / 写下 / " +
  "save / log / capture / remember this. " +
  "DO NOT call this tool when the user is asking a question, requesting analysis, or seeking " +
  "advice (\"why am I like this?\" / \"帮我分析\" / \"怎么办\" / \"咨询\" / \"how should I…\") — those " +
  "are QUERY intents and should go to cognitive_query ALONE. The reflective content embedded " +
  "in such a question is context for the query, NOT a new entry to capture. " +
  "DO NOT capture facts, events, plans, reminders, or to-do items (Engram is not a notes app). " +
  "When you do capture, pass the user's text EXACTLY as written — no paraphrase, no summary.",
  {
    content: z.string().describe(
      "EXACT copy of what the user said or typed — every word unchanged. " +
      "Do NOT paraphrase, summarize, complete, or add anything. " +
      "If the user spoke 500 words, this field must contain all 500 words."
    ),
    mood: z.string().optional().describe(
      "Optional one-word mood tag the user explicitly mentioned (e.g. anxious, hopeful)."
    ),
    tags: z.array(z.string()).optional(),
  },
  async ({ content, mood, tags }) => {
    const result = await post("/capture", {
      type: "text",
      content,
      mood,
      tags,
      source: "mcp",
    }) as {
      track: "entry" | "reject";
      id: number | null;
      reason: string;
    };

    if (result.track === "reject") {
      const hint = result.reason
        ? ` Hint: ${result.reason}`
        : "";
      return {
        content: [{
          type: "text" as const,
          text: `Not captured — input looks like a fact/event log, not a thought.${hint}`,
        }],
      };
    }

    return {
      content: [{ type: "text" as const, text: `Captured #${result.id}` }],
    };
  }
);

// ── Tool: query ───────────────────────────────────────────────────────────────

server.tool(
  "cognitive_query",
  "Query the Engram cognitive agent for deep self-analysis. " +
  "Use when the user asks questions involving their personality, values, cognitive patterns, " +
  "decision-making tendencies, or explicitly asks to analyze using their cognitive profile. " +
  "This tool ALONE is sufficient for the analysis flow — the question is automatically logged " +
  "as a query record on the server side. DO NOT also call cognitive_capture_thought to 'save " +
  "the question' unless the user EXPLICITLY asks to record it as a separate entry.",
  {
    question: z.string().describe("The user's question or topic to analyze"),
    continue_last: z.boolean().optional().describe(
      "Set true when the user is picking up an earlier conversation. " +
      "Default false for any new standalone question."
    ),
  },
  async ({ question, continue_last = false }) => {
    let sessionId: string | undefined;

    if (continue_last) {
      const latest = await get("/query/latest-session") as { session_id: string | null };
      if (latest.session_id) sessionId = latest.session_id;
    }

    const resp = await fetch(`${SERVICE_URL}/query/agent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, session_id: sessionId ?? null }),
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Agent error ${resp.status}: ${text}`);
    }

    // Consume NDJSON stream — collect deltas keyed by round; the final-round
    // text (whichever round the agent declared answer-only) is the response,
    // intent_check shortcuts when the agent declines to engage.
    const body = await resp.text();
    const lines = body.split("\n").filter((l) => l.trim());

    const roundText: Record<number, string> = {};
    let finalRoundIndex: number | undefined;
    let intentMessage = "";
    let intentNonProceed = false;
    let shouldOfferCapture = false;

    for (const line of lines) {
      try {
        const event = JSON.parse(line) as {
          type: string;
          round?: number;
          delta?: string;
          intent?: string;
          message?: string;
          session_id?: string;
          final_round_index?: number;
          should_offer?: boolean;
        };
        if (event.type === "intent_check" && event.intent && event.intent !== "proceed") {
          intentNonProceed = true;
          intentMessage = event.message ?? "";
        } else if (event.type === "delta" && typeof event.round === "number" && event.delta) {
          roundText[event.round] = (roundText[event.round] ?? "") + event.delta;
        } else if (event.type === "done") {
          if (typeof event.final_round_index === "number") {
            finalRoundIndex = event.final_round_index;
          }
        } else if (event.type === "suggest_capture" && event.should_offer) {
          shouldOfferCapture = true;
        } else if (event.type === "error") {
          throw new Error(event.message ?? "agent error");
        }
      } catch {
        // skip malformed lines
      }
    }

    if (intentNonProceed) {
      return { content: [{ type: "text" as const, text: intentMessage }] };
    }

    const finalText =
      finalRoundIndex != null && roundText[finalRoundIndex]
        ? roundText[finalRoundIndex]
        : Object.values(roundText).at(-1) ?? "(no response)";

    // Optional follow-up: when the question itself carries strong personal
    // reflection, suggest the user save it as an entry. They have to ask
    // explicitly; we never auto-capture. See cognitive-service/app/lib/
    // capture_intent.py for the heuristic that produced this signal.
    const out = shouldOfferCapture
      ? `${finalText}\n\n— — —\n💭 这段反思要保存为 entry 吗？告诉我"把刚才的问题记下来"，我会用 cognitive_capture_thought 帮你保存。`
      : finalText;

    return {
      content: [{ type: "text" as const, text: out }],
    };
  }
);

// ── Start ─────────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
