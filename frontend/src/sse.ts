// SSE consumer over fetch (EventSource only does GET; we POST the prompt).
// Parses text/event-stream framing: events are separated by blank lines;
// each line is either `event: <name>` or `data: <payload>`.

export type SseEvent = { event: string; data: string };

export async function* streamGenerate(
  prompt: string,
  signal: AbortSignal,
  sessionId?: string,
): AsyncGenerator<SseEvent> {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ prompt, session_id: sessionId ?? null }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`generate failed: ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      const ev = parseFrame(frame);
      if (ev) yield ev;
    }
  }
}

function parseFrame(frame: string): SseEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const raw of frame.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (!line || line.startsWith(":")) continue;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    const val = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
    if (field === "event") event = val;
    else if (field === "data") dataLines.push(val);
  }
  if (!dataLines.length && event === "message") return null;
  return { event, data: dataLines.join("\n") };
}
