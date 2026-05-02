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
  "Capture a user's thought, reflection, idea, observation, decision, or emotional self-analysis " +
  "into the Engram cognitive graph. " +
  "Use ONLY when the user is expressing how they THINK or FEEL about something — not for events, " +
  "plans, reminders, or factual logs (Engram is not a notes app). " +
  "Pass the user's text EXACTLY as written — no paraphrase, no summary, no additions.",
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
  "Query the Engram cognitive graph for deep self-analysis. " +
  "Use when the user asks questions involving their personality, values, cognitive patterns, " +
  "decision-making tendencies, or explicitly asks to analyze using their cognitive profile.",
  {
    question: z.string().describe("The user's question or topic to analyze"),
    mode: z.enum(["full", "fast"]).optional().describe(
      "full (default): baseline + persona + graph + synthesis. fast: graph + synthesis only."
    ),
    continue_last: z.boolean().optional().describe(
      "Set true when the user is picking up an earlier conversation. " +
      "Default false for any new standalone question."
    ),
  },
  async ({ question, mode = "full", continue_last = false }) => {
    let sessionId: string | undefined;

    if (continue_last) {
      const latest = await get("/query/latest-session") as { session_id: string | null };
      if (latest.session_id) sessionId = latest.session_id;
    }

    const resp = await fetch(`${SERVICE_URL}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode, session_id: sessionId ?? null }),
    });

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Query error ${resp.status}: ${text}`);
    }

    // Consume NDJSON stream
    const body = await resp.text();
    const lines = body.split("\n").filter((l) => l.trim());

    const stages: Record<string, string> = {
      baseline: "",
      persona_blindspot: "",
      graph_insight: "",
      intent_check: "",
    };
    let finalSessionId = sessionId;

    for (const line of lines) {
      try {
        const event = JSON.parse(line) as {
          type: string;
          stage?: string;
          delta?: string;
          session_id?: string;
          message?: string;
        };
        if (event.type === "delta" && event.stage && event.delta && event.stage in stages) {
          stages[event.stage] += event.delta;
        }
        if (event.type === "done" && event.session_id) {
          finalSessionId = event.session_id;
        }
        if (event.type === "error") {
          throw new Error(event.message ?? "query pipeline error");
        }
      } catch {
        // skip malformed lines
      }
    }

    void finalSessionId;

    if (stages.intent_check) {
      return {
        content: [{ type: "text" as const, text: stages.intent_check }],
      };
    }

    const sections: string[] = [];
    if (stages.baseline) sections.push(`## Baseline\n\n${stages.baseline}`);
    if (stages.persona_blindspot) sections.push(`## Persona lens\n\n${stages.persona_blindspot}`);
    if (stages.graph_insight) sections.push(`## Graph insight\n\n${stages.graph_insight}`);

    const output = sections.length > 0 ? sections.join("\n\n") : "(No relevant content in graph)";

    return {
      content: [{ type: "text" as const, text: output }],
    };
  }
);

// ── Start ─────────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
