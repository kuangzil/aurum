import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("./chat-api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } });
const { sendChatMessage, ChatApiError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);
const request = { session_id: "test", message: "gold momentum" };
const result = { session_id: "test", reply: "Synthetic evidence — only", status: "completed", mode: "mock", trace: [] };

function streamResponse(text) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      // Split every byte, including within Unicode and JSON tokens.
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  }), { headers: { "Content-Type": "application/x-ndjson" } });
}

test("chat consumes fragmented progress and the final response", async (t) => {
  const progress = { agent: "a2a", stage: "sent", detail: "Research → validation" };
  t.mock.method(globalThis, "fetch", async () => streamResponse(
    JSON.stringify({ type: "progress", event: progress }) + "\n" + JSON.stringify({ type: "result", result }),
  ));
  const events = [];
  assert.deepEqual(await sendChatMessage(request, [], (event) => events.push(event)), result);
  assert.deepEqual(events, [progress]);
});

test("chat reports a truncated response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => streamResponse('{"type":"progress","event":{}}\n'));
  await assert.rejects(sendChatMessage(request, [], () => {}), /before a final result/);
});

test("chat surfaces backend stream failures", async (t) => {
  t.mock.method(globalThis, "fetch", async () => streamResponse('{"type":"error","error":"LLM failed"}\n'));
  await assert.rejects(sendChatMessage(request, [], () => {}), { name: "ChatApiError", message: "LLM failed" });
});

test("chat retains JSON response and HTTP error support", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(result));
  assert.deepEqual(await sendChatMessage(request), result);
  fetch.mock.mockImplementation(async () => Response.json({ error: "Backend unavailable" }, { status: 503 }));
  await assert.rejects(sendChatMessage(request), ChatApiError);
});
