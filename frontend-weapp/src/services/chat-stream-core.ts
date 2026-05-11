import type { ChatStreamDiagnostics } from "../types/api";

export interface ParsedSSEMessage {
  event: string;
  data: string;
}

export function decodeUtf8(buffer: ArrayBuffer, decoder: TextDecoder | null): string {
  const bytes = new Uint8Array(buffer);
  if (decoder) {
    return decoder.decode(bytes, { stream: true });
  }

  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  try {
    return decodeURIComponent(escape(binary));
  } catch {
    return binary;
  }
}

export function createSSEParser(onMessage: (message: ParsedSSEMessage) => void) {
  let buffer = "";
  let eventName = "";
  let dataLines: string[] = [];

  function dispatch() {
    if (dataLines.length === 0) {
      eventName = "";
      return;
    }
    onMessage({
      event: eventName || "message",
      data: dataLines.join("\n")
    });
    eventName = "";
    dataLines = [];
  }

  function consumeLine(rawLine: string) {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line) {
      dispatch();
      return;
    }
    if (line.startsWith(":")) {
      return;
    }
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      return;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  return {
    push(chunk: string) {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      lines.forEach(consumeLine);
    },
    flush() {
      if (buffer) {
        consumeLine(buffer);
        buffer = "";
      }
      dispatch();
    }
  };
}

export function recordStreamChunkDiagnostics(
  diagnostics: ChatStreamDiagnostics,
  elapsedMs: number
) {
  const isFirstChunk = diagnostics.firstChunkMs === undefined;
  diagnostics.chunkCount = (diagnostics.chunkCount || 0) + 1;
  if (isFirstChunk) {
    diagnostics.firstChunkMs = elapsedMs;
  }
  return { force: isFirstChunk };
}

export function recordStreamEventDiagnostics(
  diagnostics: ChatStreamDiagnostics,
  eventName: string,
  data: any,
  elapsedMs: number
) {
  diagnostics.parsedEventCount = (diagnostics.parsedEventCount || 0) + 1;
  let force = false;
  if (eventName === "answer_delta") {
    const mode = typeof data?.streaming_mode === "string" ? data.streaming_mode : "token";
    const synthetic = Boolean(data?.is_synthetic_delta);
    if (mode === "token" && !synthetic) {
      diagnostics.realTokenDeltaCount = (diagnostics.realTokenDeltaCount || 0) + 1;
      if (diagnostics.firstRealTokenDeltaMs === undefined) {
        diagnostics.firstRealTokenDeltaMs = elapsedMs;
        force = true;
      }
    } else {
      diagnostics.syntheticDeltaCount = (diagnostics.syntheticDeltaCount || 0) + 1;
      diagnostics.degradedReason = diagnostics.degradedReason || "node_synthetic_delta";
      force = diagnostics.syntheticDeltaCount === 1;
    }
  }
  return { force };
}
