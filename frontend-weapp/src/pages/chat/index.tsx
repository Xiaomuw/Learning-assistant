import { useEffect, useMemo, useRef, useState } from "react";
import { useDidShow, useUnload } from "@tarojs/taro";
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
  setChatDraft,
  setStoredNotebookId,
  setStoredQuiz,
  setStoredSessionId
} from "@/store/learning";
import { DEFAULT_NOTEBOOK_ID, type ChatMessage, type Notebook } from "@/types/api";
import "./index.scss";

const STARTER_MESSAGES: ChatMessage[] = [
  {
    role: "assistant",
    content: "你好，我是你的学习助手。可以问知识点、让我拆题，也可以直接让我出几道练习。",
    timestamp: Date.now()
  }
];

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(STARTER_MESSAGES);
  const [inputValue, setInputValue] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamText, setStreamText] = useState("");
  const [statusText, setStatusText] = useState("");
  const [notebooks, setNotebooks] = useState<Notebook[]>([]);
  const [notebookError, setNotebookError] = useState("");
  const [selectedNotebookId, setSelectedNotebookId] = useState(DEFAULT_NOTEBOOK_ID);
  const [sessionId, setSessionId] = useState("");
  const streamTaskRef = useRef<{ abort: () => void } | null>(null);
  const answerRef = useRef("");

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

  function handleNotebookChange(event: any) {
    const index = Number(event.detail.value || 0);
    const notebook = notebooks[index];
    if (!notebook) return;
    setSelectedNotebookId(notebook.id);
    setStoredNotebookId(notebook.id);
  }

  function finalizeAssistantMessage(content: string, isError = false) {
    const text = content.trim() || "本轮没有返回内容，请稍后重试。";
    setMessages((current) => [
      ...current,
      { role: "assistant", content: text, timestamp: Date.now(), isError }
    ]);
    answerRef.current = "";
    setStreamText("");
    setStatusText("");
    setIsStreaming(false);
    streamTaskRef.current = null;
  }

  function handleStreamEvent(eventName: string, data: any) {
    if (eventName === "status") {
      const message = data?.message || data?.rag_warning || data?.web_search_diagnosis || "";
      if (message) setStatusText(message);
      return;
    }

    if (eventName === "routing") {
      setStatusText(data?.route ? `已选择路线：${data.route}` : "正在判断问题类型");
      return;
    }

    if (eventName === "answer_delta") {
      const delta = data?.delta || "";
      if (delta) {
        answerRef.current += delta;
        setStreamText(answerRef.current);
      }
      return;
    }

    if (eventName === "explanation") {
      const finalAnswer = data?.final_answer || data?.explanation?.thinking || "";
      if (finalAnswer) {
        answerRef.current = finalAnswer;
        setStreamText(finalAnswer);
      }
      setStatusText("正在整理回答");
      return;
    }

    if (eventName === "quiz") {
      const quizItems = Array.isArray(data?.quiz_items) ? data.quiz_items : [];
      if (quizItems.length > 0) {
        setStoredQuiz(quizItems, {
          sessionId: data?.session_id || sessionId || getStoredSessionId(),
          subjectId: data?.subject_id || selectedNotebookId || DEFAULT_NOTEBOOK_ID
        });
        setStatusText(`已生成 ${quizItems.length} 道练习题`);
      }
      if (data?.final_answer) {
        answerRef.current = data.final_answer;
        setStreamText(data.final_answer);
      }
    }
  }

  async function handleSend() {
    const question = inputValue.trim();
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user || !question || isStreaming) return;

    const nextSessionId = sessionId || createSessionId();
    setSessionId(nextSessionId);
    setStoredSessionId(nextSessionId);
    answerRef.current = "";

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
        subject_id: selectedNotebookId || DEFAULT_NOTEBOOK_ID
      },
      {
        onEvent: ({ event, data }) => handleStreamEvent(event, data),
        onDone: () => finalizeAssistantMessage(answerRef.current),
        onError: (error) => finalizeAssistantMessage(error.message || "聊天连接中断", true)
      }
    );
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
            </View>
          </View>
        ))}
        {isStreaming ? (
          <View className="message-row assistant">
            <View className="message-bubble streaming">
              <Text className="message-role">{statusText || "正在生成"}</Text>
              <Text className="message-content">{streamText || "学习引擎正在处理..."}</Text>
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
