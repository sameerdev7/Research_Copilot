import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, streamMessage } from "./api";
import type { StreamEvent } from "./types";

function streamOf(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, { status: 200 });
}

async function collect(): Promise<StreamEvent[]> {
  const events: StreamEvent[] = [];
  for await (const event of streamMessage(1, "q")) events.push(event);
  return events;
}

afterEach(() => vi.unstubAllGlobals());

describe("streamMessage", () => {
  it("yields one event per line, even when a line is split across chunks", async () => {
    const stage = JSON.stringify({ type: "stage", stage: "retrieve", attempt: 1 });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(streamOf([stage.slice(0, 10), stage.slice(10) + "\n" + stage + "\n"])));

    const events = await collect();

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ type: "stage", stage: "retrieve" });
  });

  it("turns a JSON error body into an ApiError with the server's diagnosis", async () => {
    const body = { error: { code: "no_papers", message: "No papers", hint: "Add some" } };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 400 })));

    const error = await collect().catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.info).toEqual(body.error);
  });

  it("explains a gateway error that did not come from Django", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad Gateway", { status: 502 })));

    const error = await collect().catch((e) => e);

    expect(error.info.code).toBe("server_unreachable");
  });

  it("reports an unreachable network as network_error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const error = await collect().catch((e) => e);

    expect(error.info.code).toBe("network_error");
  });
});
