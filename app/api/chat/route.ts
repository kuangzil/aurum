export const maxDuration = 120;

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: "Invalid JSON request." }, { status: 400 });
  }
  if (!body || typeof body !== "object" ||
      !("session_id" in body) || typeof body.session_id !== "string" ||
      !("message" in body) || typeof body.message !== "string") {
    return Response.json({ error: "session_id and message must be strings." }, { status: 400 });
  }
  const sessionId = body.session_id.trim();
  const message = body.message.trim();
  if (!sessionId || !message || sessionId.length > 200 || message.length > 4000) {
    return Response.json({ error: "Provide a session_id (1–200 characters) and message (1–4000 characters)." }, { status: 400 });
  }
  const streaming = request.headers.get("accept")?.includes("application/x-ndjson");
  try {
    const baseUrl = (process.env.RESEARCH_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    const response = await fetch(`${baseUrl}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: streaming ? "application/x-ndjson" : "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(110_000)]),
    });
    if (!response.ok) {
      return Response.json(
        { error: response.status === 504 ? "Research request timed out." : "Research backend could not complete the request. Check its configuration and logs." },
        { status: response.status === 504 ? 504 : 502 },
      );
    }
    return new Response(response.body, {
      headers: {
        "Content-Type": response.headers.get("content-type") || "application/json",
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return Response.json(
      { error: timedOut ? "Research request timed out." : "Research backend unavailable. Start the Python Research API and try again." },
      { status: timedOut ? 504 : 503 },
    );
  }
}
