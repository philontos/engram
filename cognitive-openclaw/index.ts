import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { Type } from "@sinclair/typebox";

const DEFAULT_SERVICE_URL = "http://127.0.0.1:18080";

async function callService(
  serviceUrl: string,
  path: string,
  body: unknown,
  method: "GET" | "POST" = "POST"
): Promise<unknown> {
  console.log(
    `[cognitive] callService start method=${method} path=${path} serviceUrl=${serviceUrl}`
  );
  const resp = await fetch(`${serviceUrl}${path}`, {
    method,
    headers: method === "POST" ? { "Content-Type": "application/json" } : {},
    body: method === "POST" ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const text = await resp.text();
    console.error(
      `[cognitive] callService failed method=${method} path=${path} status=${resp.status} body=${text}`
    );
    throw new Error(`Service error ${resp.status}: ${text}`);
  }
  console.log(
    `[cognitive] callService success method=${method} path=${path} status=${resp.status}`
  );
  return resp.json();
}

export default definePluginEntry({
  id: "cognitive",
  name: "Cognitive Memory",
  description:
    "Personal cognitive runtime for capturing raw entries into memory.",

  register(api) {
    const serviceUrl =
      (api.getConfig?.("serviceUrl") as string) ?? DEFAULT_SERVICE_URL;

    console.log(`[cognitive] register plugin serviceUrl=${serviceUrl}`);

    api.on?.(
      "before_prompt_build",
      () => ({
        prependSystemContext: [
          "You have access to native Cognitive Memory runtime tools from the `cognitive` plugin.",
          "These are runtime tool calls, not shell commands, curl commands, or exec tasks.",
          "Never use exec, shell, terminal, curl, or `openclaw ...` commands for cognitive memory work.",
          "",
          "## When to capture",
          "Call `cognitive_capture_memory` when the user explicitly asks to record something in any of these scenarios:",
          "- **Note / memo**: reminders, to-dos, things to follow up on, or anything the user wants to keep track of.",
          "- **Cognitive record**: personal observations, judgments, reflections, beliefs, or lessons learned.",
          "- **Inspiration**: sudden ideas, creative sparks, hypotheses, or insights the user wants to preserve.",
          "",
          "Do NOT call the capture tool for casual conversation, questions, or requests that are not explicitly about saving something.",
          "",
          "## When to query",
          "Call `cognitive_query` when the user asks a question that involves their own personality, values, cognitive patterns, decision tendencies, or explicitly mentions using their cognitive system, profile, or memory graph.",
          "Trigger phrases include: '结合我的画像', '根据我的认知', '用我的认知系统', '分析我', '我的性格', '我的价值观', or any question asking for personalized self-analysis.",
          "Set `continue_last: true` when the user references any prior conversation, regardless of how long ago — e.g. '接着刚才', '继续上次', '接上次的话题', '昨天聊的', '上个月说的', '之前那个问题', or any phrasing that implies picking up from a previous exchange. For everything else — any new standalone question — set `continue_last: false` (default).",
          "",
          "## Capture rules",
          "- Pass the user's original text to `content` EXACTLY as written. Do not rewrite, summarize, distill, complete, or add anything — including continuation signals ('我还没说完', '接着说') and recording-intent phrases ('单纯记录一下', '备忘一下'). The downstream system reads these signals directly.",
          "- CRITICAL: Never generate, infer, or complete content on behalf of the user. If the message is long, pass the full original text unchanged. Do not add a conclusion, summary, or any sentence that the user did not literally say.",
          "- Call `cognitive_capture_memory` once per user message, immediately. Do not wait, hold, or merge across messages.",
          "- Do not confirm something was remembered unless the tool call succeeded.",
          "",
          "## Quality gate",
          "Before calling the tool, apply a quick quality check:",
          "- Discard and reply '这条内容太短，没有记录。' only if the content is extremely short (< 15 chars) AND is purely an interjection or filler with no specific referent (e.g. '好烦', '哈哈哈', '嗯').",
          "- Ask one clarifying question only if the content has a clear intent but is missing essential context that cannot be inferred (e.g. no subject, no situation). Wait for the user's reply, then merge and write as one entry.",
          "- In all other cases, write immediately without asking.",
          "Err on the side of writing. Only discard or ask when it is obviously necessary.",
        ].join("\n"),
      }),
      { priority: 100 }
    );

    api.registerTool({
      name: "cognitive_query",
      description:
        "Query the user's personal cognitive graph for deep analysis. Use when the user asks questions involving their personality, values, cognitive patterns, decision-making tendencies, or explicitly asks to analyze using their cognitive system or profile.",
      parameters: Type.Object({
        question: Type.String({
          description: "The user's question or topic to analyze.",
        }),
        mode: Type.Optional(
          Type.Union([Type.Literal("full"), Type.Literal("fast")], {
            description: "full (default): baseline + persona + graph + synthesis. fast: graph + synthesis only.",
          })
        ),
        continue_last: Type.Optional(
          Type.Boolean({
            description:
              "Set true when the user references any prior conversation regardless of when ('接着刚才', '昨天聊的', '上个月说的', '之前那个话题', etc.). Set false (default) for any new standalone question.",
          })
        ),
      }),
      async execute(_id, params) {
        const mode = params.mode ?? "full";
        const continueSession = params.continue_last ?? false;

        console.log(
          `[cognitive] tool cognitive_query invoked mode=${mode} continue=${continueSession}`
        );

        let sessionId: string | undefined;

        if (continueSession) {
          const latest = await callService(serviceUrl, "/query/latest-session", undefined, "GET") as {
            session_id: string | null;
          };
          if (latest.session_id) {
            sessionId = latest.session_id;
            console.log(`[cognitive] continuing session=${sessionId}`);
          }
        }

        const resp = await fetch(`${serviceUrl}/query`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: params.question,
            mode,
            session_id: sessionId ?? null,
          }),
        });

        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(`Query service error ${resp.status}: ${text}`);
        }

        // Consume NDJSON stream, collect graph_insight deltas as the final answer
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

        console.log(
          `[cognitive] tool cognitive_query completed session=${finalSessionId} insightLength=${insight.length}`
        );

        return {
          content: [
            {
              type: "text" as const,
              text: insight || "（图谱暂无相关内容）",
            },
          ],
        };
      },
    });

    api.registerTool({
      name: "cognitive_capture_memory",
      description:
        "Primary native cognitive memory write tool for raw text capture. Preserve the user's text verbatim and store exactly one entry unless the user explicitly asks to split it.",
      parameters: Type.Object({
        type: Type.Literal("text"),
        content: Type.String({
          description:
            "EXACT copy of what the user said or typed — every word, every character, unchanged. Do NOT paraphrase, summarize, complete, or add anything. If the user spoke 500 words, this field must contain all 500 words. If you find yourself writing a sentence the user did not literally say, stop and delete it.",
        }),
        memory_type: Type.Optional(
          Type.Union([
            Type.Literal("thought"),
            Type.Literal("reflection"),
            Type.Literal("idea"),
            Type.Literal("behavior"),
            Type.Literal("emotion"),
            Type.Literal("event"),
            Type.Literal("lesson"),
          ])
        ),
        source: Type.Optional(Type.String()),
        context: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
        metadata: Type.Optional(Type.Record(Type.String(), Type.Unknown())),
        mood: Type.Optional(Type.String()),
        tags: Type.Optional(Type.Array(Type.String())),
      }),
      async execute(_id, params) {
        console.log(
          `[cognitive] tool cognitive_capture_memory invoked type=${params.type} memoryType=${params.memory_type ?? ""} contentLength=${params.content.length}`
        );
        const result = await callService(serviceUrl, "/capture", params) as {
          track: string;
          id: number | null;
          buffer_session_id: string | null;
          flushed_entry_id: number | null;
          reason: string;
        };
        console.log(`[cognitive] tool cognitive_capture_memory completed track=${result.track} id=${result.id}`);
        const trackLabel: Record<string, string> = {
          entry: "认知记录",
          memo: "备忘",
          buffer: "暂存（等待续写）",
          buffer_flushed: "缓冲已合并入认知记录",
        };
        const label = trackLabel[result.track] ?? result.track;
        const idPart = result.id != null ? ` #${result.id}` : (result.buffer_session_id ? ` buffer:${result.buffer_session_id.slice(0, 8)}` : "");
        return {
          content: [
            {
              type: "text" as const,
              text: `已${label}${idPart}`,
            },
          ],
        };
      },
    });
  },
});
