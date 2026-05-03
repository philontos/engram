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
        "Query the Engram cognitive agent for deep self-analysis. " +
        "Use when the user asks questions involving their personality, values, cognitive patterns, " +
        "decision-making tendencies, or explicitly asks to analyze using their cognitive profile. " +
        "This tool ALONE is sufficient for the analysis flow — the question is automatically logged " +
        "as a query record on the server side. DO NOT also call cognitive_capture_thought to 'save " +
        "the question' unless the user EXPLICITLY asks to record it as a separate entry.",
      parameters: Type.Object({
        question: Type.String({
          description: "The user's question or topic to analyze.",
        }),
        continue_last: Type.Optional(
          Type.Boolean({
            description:
              "Set true when the user is picking up an earlier conversation. Default false for any new standalone question.",
          })
        ),
      }),
      async execute(_id, params) {
        const continueSession = params.continue_last ?? false;

        console.log(
          `[cognitive] tool cognitive_query invoked continue=${continueSession}`
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

        const resp = await fetch(`${serviceUrl}/query/agent`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: params.question,
            session_id: sessionId ?? null,
          }),
        });

        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(`Agent error ${resp.status}: ${text}`);
        }

        // Consume NDJSON stream — collect deltas keyed by round; the final-round
        // text (whichever round the agent declared answer-only) is the response.
        // intent_check shortcuts when the agent declines to engage; suggest_capture
        // appends a follow-up hint when the question itself reads as a reflection.
        const text = await resp.text();
        const lines = text.split("\n").filter((l) => l.trim());

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

        // When the question itself carries strong personal reflection, suggest
        // the user save it as an entry. They have to ask explicitly; we never
        // auto-capture. See cognitive-service/app/lib/capture_intent.py for the
        // heuristic that produced this signal.
        const out = shouldOfferCapture
          ? `${finalText}\n\n— — —\n💭 这段反思要保存为 entry 吗？告诉我"把刚才的问题记下来"，我会用 cognitive_capture_thought 帮你保存。`
          : finalText;

        console.log(
          `[cognitive] tool cognitive_query completed responseLength=${out.length}`
        );

        return {
          content: [{ type: "text" as const, text: out }],
        };
      },
    });

    api.registerTool({
      name: "cognitive_capture_thought",
      description:
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
      parameters: Type.Object({
        content: Type.String({
          description:
            "EXACT copy of what the user said or typed — every word unchanged. Do NOT paraphrase, summarize, complete, or add anything. If the user spoke 500 words, this field must contain all 500 words.",
        }),
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
          type: "text",
          content: params.content,
          mood: params.mood,
          tags: params.tags,
          source: "openclaw",
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
