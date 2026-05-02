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
  name: "Engram Cognitive Memory",
  description:
    "Capture the user's thoughts and reflections into Engram, and query their cognitive graph for personalized self-analysis.",

  register(api) {
    const serviceUrl =
      (api.getConfig?.("serviceUrl") as string) ?? DEFAULT_SERVICE_URL;

    console.log(`[cognitive] register plugin serviceUrl=${serviceUrl}`);

    api.on?.(
      "before_prompt_build",
      () => ({
        prependSystemContext: [
          "You have access to two native Engram cognitive tools from the `cognitive` plugin.",
          "These are runtime tool calls — never use exec, shell, terminal, curl, or `openclaw ...` commands for cognitive memory work.",
          "",
          "## What Engram is",
          "Engram stores ONLY cognitive content: thoughts, reflections, ideas, decisions, observations, emotional self-analysis — anything that reveals how the user thinks.",
          "Engram is NOT a notes / journal / todo / reminder app. The backend intent gate will reject pure event logs, factual statements, or schedule items.",
          "",
          "## When to capture (call `cognitive_capture_thought`)",
          "Call when the user is expressing how they think or feel — sharing a reflection, an idea, a self-observation, a decision-in-progress, or an emotional experience they're processing. Any first-person sentence carrying interpretation, judgment, or self-observation qualifies.",
          "",
          "## When NOT to capture",
          "Do NOT call the capture tool for pure event logs (what they ate, how far they ran), reminders or schedule items, or casual conversation that isn't about saving a thought. If unsure, lean toward calling capture — the backend rejects off-spec inputs and tells the user how to rephrase.",
          "",
          "## When to query (call `cognitive_query`)",
          "Call when the user asks for personalized self-analysis grounded in their cognitive profile, prior reflections, or memory graph.",
          "Set `continue_last: true` when the user is picking up an earlier conversation; otherwise leave it false.",
          "",
          "## Capture rules",
          "- Pass the user's original text to `content` EXACTLY as written. Do not rewrite, summarize, distill, or complete. The downstream system reads the user's verbatim words.",
          "- CRITICAL: Never generate, infer, or complete content on behalf of the user. If the message is long, pass the full original text unchanged. Do not add a sentence the user did not literally say.",
          "- Call `cognitive_capture_thought` once per qualifying user message, immediately. Do not wait, hold, or merge across messages.",
          "- Do not confirm something was remembered unless the tool call succeeded.",
        ].join("\n"),
      }),
      { priority: 100 }
    );

    api.registerTool({
      name: "cognitive_query",
      description:
        "Query the user's personal cognitive graph for personalized self-analysis. Use when the user asks about their own personality, values, cognitive patterns, decision-making tendencies, or explicitly invokes their cognitive profile.",
      parameters: Type.Object({
        question: Type.String({
          description: "The user's question or topic to analyze.",
        }),
        mode: Type.Optional(
          Type.Union([Type.Literal("full"), Type.Literal("fast")], {
            description:
              "full (default): baseline + persona + graph + synthesis. fast: graph + synthesis only.",
          })
        ),
        continue_last: Type.Optional(
          Type.Boolean({
            description:
              "Set true when the user is picking up an earlier conversation. Set false (default) for any new standalone question.",
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
          const latest = (await callService(
            serviceUrl,
            "/query/latest-session",
            undefined,
            "GET"
          )) as { session_id: string | null };
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

        // Consume NDJSON stream, collect graph_insight deltas as the final answer.
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
              text: insight || "(no relevant content in graph)",
            },
          ],
        };
      },
    });

    api.registerTool({
      name: "cognitive_capture_thought",
      description:
        "Capture a thought, reflection, idea, observation, decision, or emotional self-analysis into the Engram cognitive graph. Use ONLY when the user is expressing how they THINK or FEEL — not for events, plans, reminders, or factual logs (Engram is not a notes app). Pass the user's text EXACTLY as written.",
      parameters: Type.Object({
        type: Type.Literal("text"),
        content: Type.String({
          description:
            "EXACT copy of what the user said or typed — every word unchanged. Do NOT paraphrase, summarize, complete, or add anything. If the user spoke 500 words, this field must contain all 500 words.",
        }),
        source: Type.Optional(Type.String()),
        mood: Type.Optional(
          Type.String({
            description:
              "Optional one-word mood tag the user explicitly mentioned (e.g. anxious, hopeful).",
          })
        ),
        tags: Type.Optional(Type.Array(Type.String())),
      }),
      async execute(_id, params) {
        console.log(
          `[cognitive] tool cognitive_capture_thought invoked contentLength=${params.content.length}`
        );
        const result = (await callService(serviceUrl, "/capture", {
          ...params,
          source: params.source ?? "openclaw",
        })) as {
          track: "entry" | "reject";
          id: number | null;
          reason: string;
        };
        console.log(
          `[cognitive] tool cognitive_capture_thought completed track=${result.track} id=${result.id}`
        );

        if (result.track === "reject") {
          const hint = result.reason ? ` 提示：${result.reason}` : "";
          return {
            content: [
              {
                type: "text" as const,
                text: `未记录——这条像是事件流水或备忘，不是思考内容。${hint}`,
              },
            ],
          };
        }

        return {
          content: [
            {
              type: "text" as const,
              text: `已记录 #${result.id}`,
            },
          ],
        };
      },
    });
  },
});
