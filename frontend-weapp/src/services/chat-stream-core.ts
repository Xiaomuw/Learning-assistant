import type { ChatStreamDiagnostics } from "../types/api";

export interface ParsedSSEMessage {
  event: string;
  data: string;
}

export interface ChatStreamPayloadDraft {
  user_id: string;
  session_id: string;
  question: string;
  subject_id: string;
  thinking_mode?: boolean;
  allow_web?: boolean;
}

export function buildChatStreamPayload(draft: ChatStreamPayloadDraft): ChatStreamPayloadDraft {
  return {
    user_id: draft.user_id,
    session_id: draft.session_id,
    question: draft.question,
    subject_id: draft.subject_id,
    thinking_mode: Boolean(draft.thinking_mode),
    allow_web: Boolean(draft.allow_web)
  };
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

export function normalizeApiBase(apiBase?: string): string {
  return String(apiBase || "").trim().replace(/\/+$/, "");
}

export function buildChatStreamUrl(apiBase?: string): string {
  const normalizedBase = normalizeApiBase(apiBase);
  return normalizedBase ? `${normalizedBase}/chat` : "";
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

export interface DisplayAnswerExplanation {
  topic?: string;
  steps?: string[];
}

const SHORT_FINAL_ANSWER_MAX_CHARS = 80;
const LONG_SINGLE_PARAGRAPH_MAX_CHARS = 220;
const ANALOGY_LEAD_MARKERS = [
  "想象",
  "比如",
  "举个例子",
  "打个比方",
  "就像",
  "好比",
  "类似",
  "可以把",
  "你可以把",
  "假设"
];
const ANALOGY_SCENE_MARKERS = [
  "餐厅",
  "点餐",
  "厨师",
  "服务员",
  "顾客",
  "快递",
  "外卖",
  "包裹",
  "寄件",
  "收件",
  "图书馆",
  "邮局"
];
const SECTION_HEADING_PATTERN = /((?:为什么(?:需要|要)\s*[\w\u4e00-\u9fff/+\-.#]{0,32}|[\w\u4e00-\u9fff/+\-.#]{0,32}\s*(?:是\s*什么|是什么|如何工作|怎么工作|工作方式|主要作用|作用|特点|易错点))\s*[：:])/g;

export function stripMarkdownArtifacts(text: string): string {
  return stripPlanningArtifacts(String(text || "")
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[a-zA-Z]*\n?/g, "").replace(/```/g, ""))
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim());
}

export function buildDisplayAnswerContent(
  finalAnswer: string,
  explanation?: DisplayAnswerExplanation
): string {
  const finalContent = prioritizeDefinitionSection(stripMarkdownArtifacts(finalAnswer));
  const stepContent = (explanation?.steps || [])
    .map((item) => stripMarkdownArtifacts(item))
    .filter((item) => !looksLikePlanningText(item))
    .filter(Boolean)
    .join("\n\n");
  const normalizedStepContent = prioritizeDefinitionSection(stepContent);

  if (finalContent && !looksLikePlanningText(finalContent)) {
    if (normalizedStepContent && shouldPreferStepContent(finalContent, normalizedStepContent)) {
      return dedupeDisplayAnswer(normalizedStepContent);
    }
    if (normalizedStepContent && shouldExpandShortFinalAnswer(finalContent, normalizedStepContent)) {
      return dedupeDisplayAnswer(`${finalContent}\n\n${normalizedStepContent}`);
    }
    return dedupeDisplayAnswer(finalContent);
  }

  if (normalizedStepContent) {
    return dedupeDisplayAnswer(normalizedStepContent);
  }
  if (explanation?.topic?.trim()) {
    return `我已经围绕「${stripMarkdownArtifacts(explanation.topic)}」整理好讲解了。`;
  }
  return "讲解已经准备好了。";
}

function stripPlanningArtifacts(text: string): string {
  let normalized = String(text || "");
  const patterns = [
    /(?:用户|你|您)(?:想|希望|需要|正在|是想)(?:了解|知道|询问|学习|掌握)[^。！？!?\n]{0,120}[。！？!?\n]?\s*/g,
    /(?:我|我们|下面)(?:会|将|先|来|要|可以)[^。！？!?\n]{0,120}(?:讲解|说明|解释|回答|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*/g,
    /(?:需要|可以|应该|最好)?从[^。！？!?\n]{0,100}(?:方面|角度|维度)(?:来)?(?:讲解|说明|解释|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*/g,
    /(?:按|按照)[^。！？!?\n]{0,80}(?:结构|顺序)(?:讲解|说明|解释|展开)[^。！？!?\n]{0,40}[。！？!?\n]?\s*/g
  ];
  patterns.forEach((pattern) => {
    normalized = normalized.replace(pattern, "");
  });
  return normalized
    .replace(/\s+/g, " ")
    .replace(/[，,]\s*([。！？!?])/g, "$1")
    .replace(/[：:]\s*([。！？!?])/g, "$1")
    .replace(/[，,：:]\s*$/, "。")
    .trim();
}

function looksLikePlanningText(text: string): boolean {
  return /用户想|用户希望|用户需要|需要从.*(?:方面|角度|维度).*讲解|我将|我会|下面我/.test(text);
}

function prioritizeDefinitionSection(text: string): string {
  const normalized = String(text || "").trim();
  if (!startsWithWhyNeeded(normalized)) return normalized;

  const matches: Array<{ heading: string; index: number }> = [];
  let match: RegExpExecArray | null;
  SECTION_HEADING_PATTERN.lastIndex = 0;
  while ((match = SECTION_HEADING_PATTERN.exec(normalized)) !== null) {
    matches.push({ heading: String(match[1] || ""), index: match.index });
  }
  SECTION_HEADING_PATTERN.lastIndex = 0;
  if (matches.length < 2) return normalized;

  const segments = matches
    .map((item, index) => {
      const start = item.index;
      const end = index + 1 < matches.length ? matches[index + 1].index : normalized.length;
      return {
        heading: item.heading,
        text: normalized.slice(start, end).trim()
      };
    })
    .filter((item) => item.text);

  const definitionIndex = segments.findIndex((item) => item.heading.replace(/\s+/g, "").includes("是什么"));
  if (definitionIndex <= 0) return normalized;

  const ordered = [
    segments[definitionIndex],
    ...segments.slice(0, definitionIndex),
    ...segments.slice(definitionIndex + 1)
  ];
  return ordered.map((item) => item.text).join("\n\n").trim();
}

function startsWithWhyNeeded(text: string): boolean {
  const compact = String(text || "").replace(/\s+/g, "").slice(0, 80);
  return compact.startsWith("为什么需要") || compact.startsWith("为什么要");
}

function shouldPreferStepContent(finalContent: string, stepContent: string): boolean {
  if (!stepContent.trim()) return false;
  if (startsWithAnalogy(finalContent)) return true;
  return isSingleLongParagraph(finalContent, LONG_SINGLE_PARAGRAPH_MAX_CHARS);
}

function shouldExpandShortFinalAnswer(finalContent: string, stepContent: string): boolean {
  const finalLength = compactTextLength(finalContent);
  const stepLength = compactTextLength(stepContent);
  if (!finalLength || finalLength > SHORT_FINAL_ANSWER_MAX_CHARS) return false;
  return stepLength >= Math.max(36, Math.floor(finalLength * 1.4));
}

function startsWithAnalogy(text: string): boolean {
  const firstSentence = String(text || "").trim().split(/[。！？!?]/, 1)[0].slice(0, 160);
  if (!firstSentence) return false;
  const hasLeadAtStart = ANALOGY_LEAD_MARKERS.some((marker) => firstSentence.startsWith(marker));
  if (hasLeadAtStart) return true;
  const hasAnalogyCue = ANALOGY_LEAD_MARKERS.some((marker) => firstSentence.includes(marker));
  const hasScene = ANALOGY_SCENE_MARKERS.some((marker) => firstSentence.includes(marker));
  return hasAnalogyCue && hasScene;
}

function isSingleLongParagraph(text: string, maxCompactLength: number): boolean {
  const paragraphs = String(text || "").split(/\n{2,}/).map((item) => item.trim()).filter(Boolean);
  return paragraphs.length <= 1 && compactTextLength(text) > maxCompactLength;
}

function compactTextLength(text: string): number {
  return String(text || "").replace(/\s+/g, "").length;
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
