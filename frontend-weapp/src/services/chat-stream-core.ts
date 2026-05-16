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

export function dedupeDisplayAnswer(text: string): string {
  const normalized = String(text || "").trim();
  if (!normalized) return "";

  return collapseAdjacentDuplicateSentences(
    collapseAdjacentDuplicateParagraphs(normalized)
  )
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function collapseAdjacentDuplicateParagraphs(text: string): string {
  const paragraphs = text.split(/\n{2,}/).map((part) => part.trim()).filter(Boolean);
  if (paragraphs.length <= 1) return text.trim();

  const result: string[] = [];
  let previousKey = "";
  paragraphs.forEach((paragraph) => {
    const key = dedupeKey(paragraph);
    if (key && key === previousKey) return;
    result.push(paragraph);
    previousKey = key;
  });
  return result.join("\n\n");
}

function collapseAdjacentDuplicateSentences(text: string): string {
  const parts = splitSentencesWithSeparators(text);
  if (parts.length <= 1) return text.trim();

  const result: string[] = [];
  let previousKey = "";
  parts.forEach((part) => {
    const stripped = part.sentence.trim();
    const key = dedupeKey(stripped);
    if (stripped && key && key === previousKey) {
      return;
    }
    result.push(part.sentence + part.separator);
    if (stripped) previousKey = key;
  });
  return result.join("").trim();
}

function splitSentencesWithSeparators(text: string): Array<{ sentence: string; separator: string }> {
  const parts: Array<{ sentence: string; separator: string }> = [];
  let sentence = "";
  let separator = "";
  let afterSentenceEnd = false;
  const sentenceEndings = "。！？!?";

  for (const char of text) {
    if (afterSentenceEnd && /\s/.test(char)) {
      separator += char;
      continue;
    }
    if (afterSentenceEnd) {
      parts.push({ sentence, separator });
      sentence = "";
      separator = "";
      afterSentenceEnd = false;
    }
    sentence += char;
    if (sentenceEndings.includes(char)) {
      afterSentenceEnd = true;
    }
  }

  if (sentence || separator) {
    parts.push({ sentence, separator });
  }
  return parts;
}

function dedupeKey(value: string): string {
  return String(value || "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\s+/g, "")
    .replace(/[：:，,。！？!?；;]/g, "")
    .trim();
}
