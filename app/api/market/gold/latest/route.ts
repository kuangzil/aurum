import { connection } from "next/server";

export async function GET() {
  await connection();
  const response = await fetch(new URL("/market/gold/latest", process.env.RESEARCH_API_URL), {
    cache: "no-store",
  });

  return new Response(response.body, {
    status: response.status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store" },
  });
}
