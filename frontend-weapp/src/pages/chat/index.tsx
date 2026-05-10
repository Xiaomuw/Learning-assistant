import { useEffect, useMemo, useRef, useState } from "react";
import Taro, { useDidShow, useUnload } from "@tarojs/taro";
import { Button, Picker, ScrollView, Text, Textarea, View } from "@tarojs/components";
import { ensureAuthSession, fetchNotebooks } from "@/services/api";
import { sendChatStream } from "@/services/chat-stream";
import { requireAuthUser } from "@/store/auth";
import {
  clearChatDraft,
  clearStoredSessionId,
  createSessionId,
  getChatDraft,
  getStoredNotebookId,
  getStoredSessionId,
  appendStoredQuiz,
  setChatDraft,
  setLearningStoreUser,
  setStoredMemory,
  setStoredNotebookId,
  setStoredSessionId
} from "@/store/learning";
import {
  DEFAULT_NOTEBOOK_ID,
  type ChatMessage,
  type ChatProcessStage,
  type Explanation,
  type Notebook,
  type QuizClarificationPanel,
  type QuizItem,
  type QuizRequestResolution
} from "@/types/api";
import "./index.scss";

const STARTER_MESSAGES: ChatMessage[] = [
  {
    role: "assistant",
    content: "你好，我是你的学习助手。可以问知识点、让我拆题，也可以直接让我出几道练习。",
    timestamp: Date.now()
  }
];

function stripMarkdownArtifacts(text: string) {
  return text
    .replace(/```[\s\S]*?```/g, (block) => block.replace(/```[a-zA-Z]*\n?/g, "").replace(/```/g, ""))
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();
}

function buildAnswerContent(finalAnswer: string, explanation?: Explanation) {
  if (finalAnswer.trim()) {
    return stripMarkdownArtifacts(finalAnswer);
  }
  const stepContent = (explanation?.steps || [])
    .map((item) => item.trim())
    .filter(Boolean)
    .join("\n\n");
  if (stepContent) {
    return stripMarkdownArtifacts(stepContent);
  }
  if (explanation?.topic?.trim()) {
    return `我已经围绕「${stripMarkdownArtifacts(explanation.topic)}」整理好讲解了。`;
  }
  return "";
}

function readableStatus(data: any) {
  return (
    data?.stage_label ||
    data?.message ||
    qualityFailureText(data) ||
    data?.rag_warning ||
    data?.web_search_diagnosis ||
    data?.retrieval_diagnosis ||
    data?.detail ||
    ""
  );
}

function stringifyStatusValue(value: any): string {
  if (!value) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map(stringifyStatusValue).filter(Boolean).join("；");
  }
  if (typeof value === "object") {
    return (
      value.message ||
      value.reason ||
      value.summary ||
      value.detail ||
      value.error ||
      ""
    ).toString().trim();
  }
  return String(value).trim();
}

function quizGenerationStatus(data: any) {
  return data?.quiz_generation_status || data?.generation_status || data?.quiz_quality_report || null;
}

function qualityFailureText(data: any) {
  const status = quizGenerationStatus(data) || {};
  const errors = Array.isArray(data?.errors) ? data.errors : Array.isArray(status?.errors) ? status.errors : [];
  const explicitFailure =
    stringifyStatusValue(status?.quality_failure_summary) ||
    stringifyStatusValue(data?.quality_failure_summary) ||
    stringifyStatusValue(status?.failure_summary) ||
    stringifyStatusValue(errors);
  if (explicitFailure) return explicitFailure;

  const qualityReport = status?.quality_report || data?.quiz_quality_report || data?.quality_report || {};
  const qualityFailed = qualityReport?.passed === false || status?.quality_passed === false || status?.passed === false;
  if (qualityFailed || data?.status === "failed") {
    return stringifyStatusValue(qualityReport?.summary || qualityReport?.issues || status?.message || data?.message);
  }
  return "";
}

function repairStatusText(data: any) {
  const status = quizGenerationStatus(data) || {};
  const attemptCount = Number(status?.repair_attempt_count || data?.repair_attempt_count || 0);
  const replacedCount = Number(status?.repair_replaced_count || data?.repair_replaced_count || 0);
  const modelUsed = status?.repair_model_used || data?.repair_model_used;
  const parts: string[] = [];
  if (attemptCount > 0) parts.push(`质量门修复 ${attemptCount} 轮`);
  if (replacedCount > 0) parts.push(`替换补齐 ${replacedCount} 道题`);
  if (modelUsed) parts.push(`修复模型 ${modelUsed}`);
  return parts.join("，");
}

function quizStatusDetail(data: any, addedCount = 0, totalCount = 0) {
  const failure = qualityFailureText(data);
  const repair = repairStatusText(data);
  if (addedCount > 0) {
    return [`新增 ${addedCount} 道练习题，当前队列共 ${totalCount} 道。`, repair].filter(Boolean).join(" ");
  }
  if (totalCount > 0) {
    return [`这组练习题已在队列中，当前队列共 ${totalCount} 道。`, repair].filter(Boolean).join(" ");
  }
  if (failure) {
    return `练习题未保存：${failure}`;
  }
  return repair || "需要先选择练习方向。";
}

function statusStage(data: any): ChatProcessStage {
  if (quizGenerationStatus(data) || data?.stream_stage === "quiz_quality") {
    const failure = qualityFailureText(data);
    const repair = repairStatusText(data);
    return {
      key: "quiz_quality",
      label: "练习质量检查",
      detail: failure ? `练习题未保存：${failure}` : repair || readableStatus(data) || "已完成练习题质量检查。",
      status: failure || data?.status === "failed" ? "failed" : data?.status === "completed" ? "completed" : "running"
    };
  }
  if (data?.guard || data?.allow_tools !== undefined || data?.allow_search !== undefined) {
    return {
      key: "guard",
      label: "工具守卫",
      detail: "已确认本轮工具与搜索策略。",
      status: "completed"
    };
  }
  if (data?.web_search_attempted !== undefined || data?.web_search_diagnosis) {
    return {
      key: "web_search",
      label: "网络搜索",
      detail: data?.web_search_diagnosis || (data?.web_search_used ? "已使用网络搜索补充信息。" : "未使用网络搜索。"),
      status: "completed"
    };
  }
  if (data?.context_audit || data?.verified_context) {
    return {
      key: "context_audit",
      label: "上下文审查",
      detail: "已检查可用资料和证据质量。",
      status: "completed"
    };
  }
  if (data?.retrieved_docs || data?.retrieval_relevance || data?.rag_ready !== undefined) {
    return {
      key: "retrieval",
      label: "知识检索",
      detail: data?.retrieval_diagnosis || "已完成知识库检索。",
      status: "completed"
    };
  }
  if (data?.teaching_user_state || data?.teaching_input_type) {
    return {
      key: "teaching",
      label: "教学策略",
      detail: "已根据当前问题选择讲解节奏。",
      status: "completed"
    };
  }
  return {
    key: data?.stream_stage || (data?.heartbeat ? "heartbeat" : "status"),
    label: data?.stage_label || (data?.heartbeat ? "处理中" : "准备中"),
    detail: readableStatus(data) || "学习引擎正在处理。",
    status: data?.status === "failed" ? "failed" : data?.status === "completed" ? "completed" : "running"
  };
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(STARTER_MESSAGES);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [statusText, setStatusText] = useState("");
  const [streamStages, setStreamStages] = useState<ChatProcessStage[]>([]);
  const [streamQuiz, setStreamQuiz] = useState<QuizItem[]>([]);
  const [streamClarification, setStreamClarification] = useState<QuizClarificationPanel | null>(null);
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [notebookError, setNotebookError] = useState("");
  const [selectedNotebookId, setSelectedNotebookId] = useState(DEFAULT_NOTEBOOK_ID);
  const [sessionId, setSessionId] = useState("");
  const streamTaskRef = useRef<{ abort: () => void } | null>(null);
  const answerRef = useRef("");
  const explanationRef = useRef<Explanation | undefined>();
  const quizRef = useRef<QuizItem[]>([]);
  const quizRequestRef = useRef<QuizRequestResolution | undefined>();
  const quizClarificationRef = useRef<QuizClarificationPanel | undefined>();
  const stagesRef = useRef<ChatProcessStage[]>([]);
  const reasoningRef = useRef("");
  const routeRef = useRef("");
  const questionTypeRef = useRef("");

  const selectedNotebook = useMemo(
    () => notebooks.find((item) => item.id === selectedNotebookId),
    [notebooks, selectedNotebookId]
  );
  const notebookNames = notebooks.map((item) => `${item.icon || "📘"} ${item.name}`);
  const selectedNotebookIndex = Math.max(
    0,
    notebooks.findIndex((item) => item.id === selectedNotebookId)
  );

  useDidShow(() => {
    void bootstrapChat();
  });

  async function bootstrapChat() {
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    setLearningStoreUser(user.id);
    setSelectedNotebookId(getStoredNotebookId());
    setSessionId(getStoredSessionId());
    const draft = getChatDraft();
    if (draft.length > 0) {
      setMessages(draft);
    }
    await loadNotebooks();
  }

  useEffect(() => {
    if (messages.length > 0) {
      setChatDraft(messages);
    }
  }, [messages]);

  useUnload(() => {
    streamTaskRef.current?.abort();
  });

  async function loadNotebooks() {
    try {
      setNotebookError("");
      const list = await fetchNotebooks();
      setNotebooks(list);
      const stored = getStoredNotebookId();
      const current = list.find((item) => item.id === stored) || list[0];
      if (current) {
        setSelectedNotebookId(current.id);
        setStoredNotebookId(current.id);
      }
    } catch (err: any) {
      setNotebooks([]);
      setNotebookError(err?.message || "笔记本加载失败，请稍后重试");
    }
  }

  function resetStreamRefs() {
    answerRef.current = "";
    explanationRef.current = undefined;
    quizRef.current = [];
    quizRequestRef.current = undefined;
    quizClarificationRef.current = undefined;
    stagesRef.current = [];
    reasoningRef.current = "";
    routeRef.current = "";
    questionTypeRef.current = "";
    setStreamQuiz([]);
    setStreamClarification(null);
    setStreamStages([]);
  }

  function upsertStage(stage: ChatProcessStage) {
    const next = [...stagesRef.current.filter((item) => item.key !== stage.key), stage].slice(-8);
    stagesRef.current = next;
    setStreamStages(next);
  }

  function finalizeAssistantMessage(content: string, isError = false) {
    const fallback = quizRef.current.length
      ? "我顺手帮你准备了一组练习题，去刷题页就能接着做。"
      : quizClarificationRef.current
        ? "我可以帮你出题，但需要先确定练习方向。"
        : "本轮没有返回内容，请稍后重试。";
    const text = content.trim() || fallback;
    const process = stagesRef.current.length
      ? {
          stages: stagesRef.current,
          reasoningSummary: reasoningRef.current
            ? `已接收 ${reasoningRef.current.length} 字模型思考过程，移动端仅保留摘要。`
            : undefined,
          reasoningTrace: reasoningRef.current ? "" : undefined
        }
      : undefined;
    setMessages((current) => [
      ...current,
      {
        role: "assistant",
        content: text,
        timestamp: Date.now(),
        isError,
        quiz: quizRef.current.length ? quizRef.current : undefined,
        quizRequest: quizRequestRef.current,
        quizClarification: quizClarificationRef.current,
        explanation: explanationRef.current,
        process,
        questionType: questionTypeRef.current || undefined,
        route: routeRef.current || undefined
      }
    ]);
    resetStreamRefs();
    setStreamText("");
    setStatusText("");
    setIsStreaming(false);
    streamTaskRef.current = null;
  }

  function handleStreamEvent(eventName: string, data: any) {
    if (eventName === "status") {
      const message = readableStatus(data);
      if (message) setStatusText(message);
      upsertStage(statusStage(data));
      return;
    }

    if (eventName === "routing") {
      routeRef.current = data?.route || routeRef.current;
      questionTypeRef.current = data?.question_type || questionTypeRef.current;
      const routeText = data?.route ? `已选择路线：${data.route}` : "正在判断问题类型";
      setStatusText(routeText);
      upsertStage({
        key: "routing",
        label: "问题识别",
        detail: routeText,
        status: "completed"
      });
      return;
    }

    if (eventName === "reasoning_delta") {
      const delta = data?.delta || "";
      if (delta) {
        reasoningRef.current += delta;
        setStatusText(`模型思考中：已接收 ${reasoningRef.current.length} 字`);
        upsertStage({
          key: "reasoning",
          label: "模型思考",
          detail: "正在接收模型思考过程，移动端仅显示摘要。",
          status: "running"
        });
      }
      return;
    }

    if (eventName === "answer_delta") {
      const delta = data?.delta || "";
      if (delta) {
        answerRef.current += delta;
        setStreamText(answerRef.current);
        upsertStage({
          key: "answer_stream",
          label: "正在生成回答",
          detail: "回答正文正在逐步输出。",
          status: "running"
        });
      }
      return;
    }

    if (eventName === "explanation" || eventName === "final") {
      const explanation = data?.explanation as Explanation | undefined;
      const finalAnswer = buildAnswerContent(data?.final_answer || "", explanation);
      explanationRef.current = explanation || explanationRef.current;
      routeRef.current = data?.route || routeRef.current;
      questionTypeRef.current = data?.question_type || questionTypeRef.current;
      if (finalAnswer) {
        answerRef.current = finalAnswer;
        setStreamText(finalAnswer);
      }
      setStatusText("正在整理回答");
      upsertStage({
        key: "answer",
        label: "已生成回答",
        detail: finalAnswer ? "最终回答已经准备好。" : "结构化讲解已经准备好。",
        status: "completed"
      });
      return;
    }

    if (eventName === "quiz") {
      const quizItems = Array.isArray(data?.quiz_items) ? data.quiz_items : [];
      const quizRequest = data?.quiz_request as QuizRequestResolution | undefined;
      const quizClarification = data?.quiz_clarification as QuizClarificationPanel | undefined;
      const finalAnswer = buildAnswerContent(data?.final_answer || "", undefined);
      quizRequestRef.current = quizRequest || quizRequestRef.current;
      quizClarificationRef.current = quizClarification || quizClarificationRef.current;
      setStreamClarification(quizClarification || null);
      let addedCount = 0;
      let totalCount = 0;
      if (quizItems.length > 0) {
        quizRef.current = quizItems;
        setStreamQuiz(quizItems);
        const appendResult = appendStoredQuiz(quizItems, {
          sessionId: data?.session_id || sessionId || getStoredSessionId(),
          subjectId: quizRequest?.subject_id || data?.subject_id || selectedNotebookId || DEFAULT_NOTEBOOK_ID
        });
        addedCount = appendResult.addedCount;
        totalCount = appendResult.totalCount;
        setStatusText(addedCount > 0 ? `已新增 ${addedCount} 道练习题` : "这组练习题已在队列中");
      }
      if (finalAnswer) {
        answerRef.current = finalAnswer;
        setStreamText(finalAnswer);
      } else if (quizClarification) {
        answerRef.current = "我可以帮你出题，但需要先确定练习方向。";
        setStreamText(answerRef.current);
      } else if (!quizItems.length && qualityFailureText(data)) {
        answerRef.current = quizStatusDetail(data);
        setStreamText(answerRef.current);
      }
      const detail = quizStatusDetail(data, addedCount, totalCount);
      upsertStage({
        key: "quiz",
        label: quizItems.length ? "练习题已准备" : quizClarification ? "练习方向待确认" : "练习题未保存",
        detail,
        status: quizItems.length || quizClarification ? "completed" : "failed"
      });
      return;
    }

    if (eventName === "memory") {
      if (data?.memory) {
        setStoredMemory(data.memory);
      }
      upsertStage({
        key: "memory",
        label: "学习记忆",
        detail: "本轮学习记忆已更新。",
        status: "completed"
      });
    }
  }

  function handleNotebookChange(event: any) {
    const index = Number(event.detail.value || 0);
    const notebook = notebooks[index];
    if (!notebook) return;
    setSelectedNotebookId(notebook.id);
    setStoredNotebookId(notebook.id);
  }

  async function sendQuestion(rawQuestion: string) {
    const question = rawQuestion.trim();
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user || !question || isStreaming) return;
    setLearningStoreUser(user.id);

    const nextSessionId = sessionId || createSessionId();
    setSessionId(nextSessionId);
    setStoredSessionId(nextSessionId);
    resetStreamRefs();

    setMessages((current) => [
      ...current,
      { role: "user", content: question, timestamp: Date.now() }
    ]);
    setInputValue("");
    setStreamText("");
    setStatusText("正在连接学习引擎");
    setIsStreaming(true);

    streamTaskRef.current = sendChatStream(
      {
        user_id: user.id,
        session_id: nextSessionId,
        question,
        subject_id: selectedNotebookId || DEFAULT_NOTEBOOK_ID,
        thinking_mode: false
      },
      {
        onEvent: ({ event, data }) => handleStreamEvent(event, data),
        onDone: () => finalizeAssistantMessage(answerRef.current),
        onError: (error) => finalizeAssistantMessage(error.message || "聊天连接中断", true)
      }
    );
  }

  function handleSend() {
    void sendQuestion(inputValue);
  }

  function handleNewChat() {
    streamTaskRef.current?.abort();
    clearStoredSessionId();
    clearChatDraft();
    setSessionId("");
    setMessages(STARTER_MESSAGES);
    setStreamText("");
    setStatusText("");
    setIsStreaming(false);
    resetStreamRefs();
  }

  function renderStages(stages: ChatProcessStage[] | undefined) {
    if (!stages?.length) return null;
    return (
      <View className="process-list">
        {stages.map((stage) => (
          <View key={stage.key} className={`process-item ${stage.status}`}>
            <Text className="process-label">{stage.label}</Text>
            <Text className="process-detail">{stage.detail}</Text>
          </View>
        ))}
      </View>
    );
  }

  function renderClarification(panel: QuizClarificationPanel | null | undefined) {
    if (!panel) return null;
    return (
      <View className="quiz-clarification">
        <Text className="quiz-card-title">{panel.title || "想练哪一块？"}</Text>
        <Text className="quiz-card-desc">{panel.description || "先选一个练习方向，我再帮你生成题包。"}</Text>
        {(panel.recommended_options || []).slice(0, 3).map((option) => (
          <Button
            key={`${option.source}-${option.value}`}
            className="button-secondary suggestion-button"
            disabled={isStreaming}
            onClick={() => void sendQuestion(`围绕 ${option.value} 出 5 道单选题`)}
          >
            {option.label || option.value}
          </Button>
        ))}
        {panel.custom_input_placeholder ? (
          <Button
            className="button-secondary suggestion-button"
            disabled={isStreaming}
            onClick={() => void sendQuestion(panel.custom_input_placeholder)}
          >
            {panel.custom_input_placeholder}
          </Button>
        ) : null}
      </View>
    );
  }

  function renderQuizPreview(quiz: QuizItem[] | undefined) {
    if (!quiz?.length) return null;
    return (
      <View className="quiz-preview">
        <View className="quiz-preview-header">
          <View>
            <Text className="quiz-card-title">练习题已经打包好了</Text>
            <Text className="quiz-card-desc">共 {quiz.length} 道题，进入刷题页继续。</Text>
          </View>
          <Button className="button-secondary quiz-link-button" onClick={() => Taro.switchTab({ url: "/pages/practice/index" })}>
            去刷题
          </Button>
        </View>
        {quiz.slice(0, 3).map((item, index) => (
          <View key={`${item.question_id || item.question}-${index}`} className="quiz-preview-item">
            <Text className="quiz-preview-meta">{item.difficulty || "练习"} · {item.knowledge_point || item.concept_name || "综合"}</Text>
            <Text className="quiz-preview-question">{item.question}</Text>
          </View>
        ))}
      </View>
    );
  }

  return (
    <View className="page chat-page">
      <View className="chat-header">
        <View>
          <Text className="page-title">问答</Text>
          <Text className="page-subtitle">当前笔记本：{selectedNotebook?.name || "默认知识库"}</Text>
        </View>
        <Button className="button-secondary header-button" onClick={handleNewChat}>
          新对话
        </Button>
      </View>

      <Picker mode="selector" range={notebookNames} value={selectedNotebookIndex} onChange={handleNotebookChange}>
        <View className="card notebook-picker">
          <Text className="notebook-picker-label">切换笔记本</Text>
          <Text className="notebook-picker-value">{selectedNotebook?.name || "默认知识库"}</Text>
        </View>
      </Picker>

      {notebookError ? (
        <View className="card error-card">
          <Text>{notebookError}</Text>
          <Button className="button-secondary retry-button" onClick={loadNotebooks}>
            重试
          </Button>
        </View>
      ) : null}

      <ScrollView className="message-list" scrollY scrollIntoView="chat-bottom">
        {messages.map((message, index) => (
          <View key={`${message.timestamp}-${index}`} className={`message-row ${message.role}`}>
            <View className={`message-bubble ${message.isError ? "error" : ""}`}>
              <Text className="message-role">{message.role === "user" ? "你" : "Coach"}</Text>
              <Text className="message-content">{message.content}</Text>
              {message.role === "assistant" ? renderStages(message.process?.stages) : null}
              {renderClarification(message.quizClarification)}
              {renderQuizPreview(message.quiz)}
            </View>
          </View>
        ))}
        {isStreaming ? (
          <View className="message-row assistant">
            <View className="message-bubble streaming">
              <Text className="message-role">{statusText || "正在生成"}</Text>
              <Text className="message-content">{streamText || "学习引擎正在处理..."}</Text>
              {renderStages(streamStages)}
              {renderClarification(streamClarification)}
              {renderQuizPreview(streamQuiz)}
            </View>
          </View>
        ) : null}
        <View id="chat-bottom" />
      </ScrollView>

      <View className="composer card">
        <Textarea
          className="composer-input"
          value={inputValue}
          autoHeight
          maxlength={2000}
          placeholder="输入你的问题..."
          disabled={isStreaming}
          onInput={(event: any) => setInputValue(event.detail.value)}
        />
        <Button className="button-primary composer-button" disabled={!inputValue.trim() || isStreaming} onClick={handleSend}>
          {isStreaming ? "生成中" : "发送"}
        </Button>
      </View>
    </View>
  );
}
