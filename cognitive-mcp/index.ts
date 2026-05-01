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
  "cognitive_capture_memory",
  "Write a memory to the Engram cognitive graph. " +
  "Pass the user's text EXACTLY as written — do not paraphrase, summarize, or add anything. " +
  "Call once per message, immediately.",
  {
    content: z.string().describe(
      "EXACT copy of what the user said or typed — every word, every character, unchanged. " +
      "Do NOT paraphrase, summarize, complete, or add anything. " +
      "If the user spoke 500 words, this field must contain all 500 words."
    ),
    memory_type: z.enum([
      "thought", "reflection", "idea", "behavior", "emotion", "event", "lesson"
    ]).optional().describe("Type of memory entry"),
    mood: z.string().optional(),
    tags: z.array(z.string()).optional(),
  },
  async ({ content, memory_type, mood, tags }) => {
    const result = await post("/capture", {
      type: "text",
      content,
      memory_type,
      mood,
      tags,
      source: "mcp",
    }) as {
      track: string;
      id: number | null;
      buffer_session_id: string | null;
    };

    const trackLabel: Record<string, string> = {
      entry: "Captured",
      memo: "Saved as memo",
      buffer: "Buffered (awaiting continuation)",
      buffer_flushed: "Buffer merged into entry",
    };
    const label = trackLabel[result.track] ?? result.track;
    const idPart = result.id != null
      ? ` #${result.id}`
      : result.buffer_session_id
        ? ` (buffer ${result.buffer_session_id.slice(0, 8)})`
        : "";

    return {
      content: [{ type: "text" as const, text: `${label}${idPart}` }],
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
      "Set true when the user references any prior conversation " +
      "('继续上次', '接着刚才', etc.). Default false."
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
    const text = await resp.text();
    const lines = text.split("\n").filter((l) => l.trim());

    let insight = "";
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
        if (event.type === "delta" && event.stage === "graph_insight" && event.delta) {
          insight += event.delta;
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

    return {
      content: [{ type: "text" as const, text: insight || "(No relevant content in graph)" }],
    };
  }
);

// ── Start ─────────────────────────────────────────────────────────────────────

const transport = new StdioServerTransport();
await server.connect(transport);
