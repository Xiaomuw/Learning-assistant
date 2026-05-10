import { useMemo, useState } from "react";
import Taro, { useDidShow } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import {
  createPracticePack,
  ensureAuthSession,
  fetchLatestQuizBundle,
  fetchPracticeRecommendations,
  submitPracticeAttempt
} from "@/services/api";
import { requireAuthUser } from "@/store/auth";
import {
  clearLearningCenterTarget,
  createSessionId,
  getLearningCenterTarget,
  getStoredNotebookId,
  getStoredQuizState,
  setLearningStoreUser,
  setStoredNotebookId,
  setStoredQuizState,
  setStoredSessionId,
  type StoredQuizState
} from "@/store/learning";
import type { LearningCenterPracticeTarget, OptionKey, PracticeAttemptResult, QuizItem } from "@/types/api";
import "./index.scss";

const OPTION_KEYS: OptionKey[] = ["A", "B", "C", "D"];

function quizKey(quiz: QuizItem | undefined, index: number) {
  return quiz?.question_id || `${index}:${quiz?.question || "quiz"}`;
}

function validOptions(quiz: QuizItem | undefined) {
  return Array.isArray(quiz?.options) ? quiz.options : [];
}

function isUsableQuiz(quiz: QuizItem | undefined) {
  const options = validOptions(quiz);
  return Boolean(
    quiz?.question &&
      OPTION_KEYS.every((key) => options.some((option) => option.key === key && option.text)) &&
      OPTION_KEYS.includes(quiz.correct_option as OptionKey)
  );
}

function normalizeQuizItem(item: QuizItem, subjectId: string, sessionId: string, target?: LearningCenterPracticeTarget): QuizItem {
  return {
    ...item,
    subject_id: item.subject_id || subjectId,
    notebook_id: item.notebook_id || subjectId,
    source_session_id: item.source_session_id || sessionId,
    concept_id: item.concept_id || target?.conceptId,
    concept_name: item.concept_name || target?.conceptName,
    topic_id: item.topic_id || target?.topicId,
    chapter_id: item.chapter_id || target?.chapterId,
    knowledge_point: item.knowledge_point || target?.conceptName || "综合"
  };
}

function quizIdentity(item: QuizItem) {
  const id = item.question_id?.trim();
  if (id) return `id:${id}`;
  return `${item.question || ""}|${(item.options || []).map((option) => option.text).join("|")}|${item.correct_option}`.toLowerCase();
}

function mergeQuizItems(current: QuizItem[], incoming: QuizItem[]) {
  const seen = new Set<string>();
  const result: QuizItem[] = [];
  for (const item of [...current, ...incoming]) {
    const identity = quizIdentity(item);
    if (identity && seen.has(identity)) continue;
    if (identity) seen.add(identity);
    result.push(item);
  }
  return result;
}

function hintText(hint: string) {
  return hint.replace(/正确答案[:：]?\s*[A-D]/gi, "关键判断点").trim();
}

function scoreText(score: number | undefined) {
  const value = Number(score || 0);
  return `${Math.round(value > 1 ? value : value * 100)}%`;
}

export default function PracticePage() {
  const [quizList, setQuizList] = useState<QuizItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState("");
  const [feedback, setFeedback] = useState<PracticeAttemptResult | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [notebookId, setNotebookId] = useState(getStoredNotebookId());
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [showHint, setShowHint] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [generatingPack, setGeneratingPack] = useState(false);
  const [error, setError] = useState("");

  const currentQuiz = quizList[currentIndex];
  const currentOptions = validOptions(currentQuiz);
  const currentQuizKey = quizKey(currentQuiz, currentIndex);
  const isLegacyQuiz = Boolean(currentQuiz && !isUsableQuiz(currentQuiz));
  const selectedOptionText = currentOptions.find((option) => option.key === (feedback?.selected_option || selectedOption))?.text || "";
  const correctOptionText = feedback
    ? currentOptions.find((option) => option.key === feedback.correct_option)?.text || ""
    : "";
  const selectedRationale = feedback
    ? feedback.option_rationales?.[feedback.selected_option || selectedOption] || ""
    : "";
  const correctRationale = feedback ? feedback.option_rationales?.[feedback.correct_option] || "" : "";
  const progressText = useMemo(() => {
    if (!quizList.length) return "0 / 0";
    return `${currentIndex + 1} / ${quizList.length}`;
  }, [currentIndex, quizList.length]);

  useDidShow(() => {
    void bootstrapPractice();
  });

  async function bootstrapPractice() {
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    setLearningStoreUser(user.id);
    await loadQuiz(user.id);
  }

  function persistState(partial: Partial<StoredQuizState> = {}) {
    const nextFeedback = partial.feedback !== undefined ? partial.feedback : feedback;
    setStoredQuizState({
      sessionId,
      subjectId: notebookId,
      items: quizList,
      currentIndex,
      answers,
      feedback: nextFeedback ?? null,
      feedbackQuizKey: partial.feedbackQuizKey ?? (nextFeedback ? currentQuizKey : ""),
      isCompleted,
      ...partial
    });
  }

  function hydratePractice(items: QuizItem[], nextSessionId: string, nextNotebookId: string, partial: Partial<StoredQuizState> = {}) {
    const nextIndex = Math.min(partial.currentIndex || 0, Math.max(items.length - 1, 0));
    const nextAnswers = partial.answers || {};
    const nextQuizKey = quizKey(items[nextIndex], nextIndex);
    const nextFeedback = partial.feedback && partial.feedbackQuizKey === nextQuizKey ? partial.feedback : null;
    setQuizList(items);
    setCurrentIndex(nextIndex);
    setSessionId(nextSessionId);
    setNotebookId(nextNotebookId);
    setStoredNotebookId(nextNotebookId);
    setStoredSessionId(nextSessionId);
    setAnswers(nextAnswers);
    setSelectedOption(nextFeedback?.selected_option || nextAnswers[nextQuizKey] || "");
    setFeedback(nextFeedback);
    setShowHint(false);
    setIsCompleted(Boolean(partial.isCompleted));
    setStoredQuizState({
      sessionId: nextSessionId,
      subjectId: nextNotebookId,
      items,
      currentIndex: nextIndex,
      answers: nextAnswers,
      feedback: nextFeedback,
      feedbackQuizKey: nextFeedback ? nextQuizKey : "",
      isCompleted: Boolean(partial.isCompleted),
      completedAt: partial.completedAt ?? null
    });
  }

  async function generateTargetPack(userId: string, target: LearningCenterPracticeTarget) {
    const nextSessionId = sessionId || getStoredQuizState().sessionId || createSessionId();
    setGeneratingPack(true);
    try {
      const result = await createPracticePack({
        user_id: userId,
        session_id: nextSessionId,
        subject_id: target.subjectId,
        request_text: `针对「${target.conceptName}」生成 5 道 408 风格单选题`,
        current_practice_question: null,
        last_practice_pack: [],
        context: {
          concept_id: target.conceptId,
          concept_name: target.conceptName,
          chapter_id: target.chapterId,
          topic_id: target.topicId,
          active_topic: target.conceptName,
          topic: target.conceptName
        }
      });
      const items = (result.items || []).map((item) =>
        normalizeQuizItem(item, result.subject_id || target.subjectId, nextSessionId, target)
      );
      if (!items.length) {
        setError(result.message || "定向出题暂时没有生成新题，请换个知识点再试。");
        clearLearningCenterTarget();
        return false;
      }
      hydratePractice(items, nextSessionId, result.subject_id || target.subjectId);
      clearLearningCenterTarget();
      return true;
    } catch (err: any) {
      setError(err?.message || "定向出题失败，请稍后重试");
      clearLearningCenterTarget();
      return false;
    } finally {
      setGeneratingPack(false);
    }
  }

  async function loadQuiz(userId: string) {
    setLoading(true);
    setError("");
    const target = getLearningCenterTarget();
    if (target) {
      await generateTargetPack(userId, target);
      setLoading(false);
      return;
    }

    const cached = getStoredQuizState();
    if (cached.items.length > 0) {
      const nextIndex = Math.min(cached.currentIndex || 0, cached.items.length - 1);
      hydratePractice(cached.items, cached.sessionId || "", cached.subjectId || getStoredNotebookId(), {
        currentIndex: nextIndex,
        answers: cached.answers || {},
        feedback: cached.feedback ?? null,
        feedbackQuizKey: cached.feedbackQuizKey || "",
        isCompleted: cached.isCompleted,
        completedAt: cached.completedAt
      });
      setLoading(false);
      return;
    }

    try {
      const latest = await fetchLatestQuizBundle(userId);
      const latestItems = Array.isArray(latest.quiz_items) ? latest.quiz_items : [];
      if (latestItems.length > 0) {
        const nextSessionId = latest.session_id || createSessionId();
        const nextNotebookId = latest.subject_id || getStoredNotebookId();
        hydratePractice(
          latestItems.map((item) => normalizeQuizItem(item, nextNotebookId, nextSessionId)),
          nextSessionId,
          nextNotebookId
        );
        return;
      }

      const recommendations = await fetchPracticeRecommendations(userId, getStoredNotebookId());
      const items = Array.isArray(recommendations.items) ? recommendations.items : [];
      const nextNotebookId = recommendations.subject_id || getStoredNotebookId();
      hydratePractice(
        items.map((item) => normalizeQuizItem(item, nextNotebookId, "")),
        "",
        nextNotebookId
      );
    } catch (err: any) {
      setError(err?.message || "暂时无法获取练习题");
    } finally {
      setLoading(false);
    }
  }

  function selectOption(key: string) {
    if (feedback || submitting || isLegacyQuiz) return;
    const nextAnswers = {
      ...answers,
      [currentQuizKey]: key
    };
    setSelectedOption(key);
    setAnswers(nextAnswers);
    persistState({ answers: nextAnswers });
    setError("");
  }

  async function handleSubmit() {
    const user = requireAuthUser();
    if (!user || !currentQuiz || !selectedOption || feedback || submitting || isLegacyQuiz) return;

    const nextSessionId = currentQuiz.source_session_id || sessionId || getStoredQuizState().sessionId || createSessionId();
    const nextNotebookId = currentQuiz.subject_id || currentQuiz.notebook_id || notebookId || getStoredQuizState().subjectId || getStoredNotebookId();
    const quizItemPayload: QuizItem = { ...currentQuiz };
    delete quizItemPayload.source_session_id;
    const nextAnswers = {
      ...answers,
      [currentQuizKey]: selectedOption
    };
    setSessionId(nextSessionId);
    setNotebookId(nextNotebookId);
    persistState({
      sessionId: nextSessionId,
      subjectId: nextNotebookId,
      answers: nextAnswers,
      feedback: null,
      feedbackQuizKey: ""
    });

    setSubmitting(true);
    setError("");
    try {
      const result = await submitPracticeAttempt({
        userId: user.id,
        sessionId: nextSessionId,
        notebookId: nextNotebookId,
        quizItem: quizItemPayload,
        selectedOption
      });
      setFeedback(result);
      setAnswers(nextAnswers);
      const nextIsCompleted = currentIndex >= quizList.length - 1;
      const nextCompletedAt = nextIsCompleted ? Date.now() : null;
      setIsCompleted(nextIsCompleted);
      setStoredQuizState({
        sessionId: nextSessionId,
        subjectId: nextNotebookId,
        items: quizList,
        currentIndex,
        answers: nextAnswers,
        feedback: result,
        feedbackQuizKey: currentQuizKey,
        isCompleted: nextIsCompleted,
        completedAt: nextCompletedAt
      });
    } catch (err: any) {
      setError(err?.message || "提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGenerateMore() {
    const user = requireAuthUser();
    if (!user || generatingPack) return;
    if (!currentQuiz) {
      setError("当前没有题目可作为补题上下文，请先从问答页生成一组题。");
      return;
    }
    const activeNotebookId = currentQuiz.subject_id || currentQuiz.notebook_id || notebookId || getStoredNotebookId();
    const activeSessionId = currentQuiz.source_session_id || sessionId || getStoredQuizState().sessionId || createSessionId();
    const topic = currentQuiz.concept_name || currentQuiz.knowledge_point || "综合";
    const currentPracticeQuestion: QuizItem = { ...currentQuiz, knowledge_point: topic };
    setGeneratingPack(true);
    setError("");
    try {
      const result = await createPracticePack({
        user_id: user.id,
        session_id: activeSessionId,
        subject_id: activeNotebookId,
        request_text: "AI补题",
        current_practice_question: currentPracticeQuestion,
        last_practice_pack: quizList,
        context: {
          topic,
          active_topic: topic,
          current_question_topic: topic
        }
      });
      const incoming = (result.items || []).map((item) =>
        normalizeQuizItem(item, result.subject_id || activeNotebookId, activeSessionId)
      );
      const nextQuizList = mergeQuizItems(quizList, incoming);
      if (nextQuizList.length <= quizList.length) {
        setError(result.message || "这次没有生成新的题，请稍后再试。");
        return;
      }
      const shouldJumpToNewItems = isCompleted || isLegacyQuiz || currentIndex >= quizList.length - 1;
      const nextIndex = shouldJumpToNewItems ? quizList.length : currentIndex;
      const nextFeedback = shouldJumpToNewItems ? null : feedback;
      const nextSelectedOption = shouldJumpToNewItems ? "" : selectedOption;
      setQuizList(nextQuizList);
      setCurrentIndex(nextIndex);
      setFeedback(nextFeedback);
      setSelectedOption(nextSelectedOption);
      setShowHint(false);
      setIsCompleted(false);
      setSessionId(activeSessionId);
      setNotebookId(result.subject_id || activeNotebookId);
      setStoredQuizState({
        sessionId: activeSessionId,
        subjectId: result.subject_id || activeNotebookId,
        items: nextQuizList,
        currentIndex: nextIndex,
        answers,
        feedback: nextFeedback,
        feedbackQuizKey: nextFeedback ? currentQuizKey : "",
        isCompleted: false,
        completedAt: null
      });
    } catch (err: any) {
      setError(err?.message || "AI 补题失败，请稍后重试");
    } finally {
      setGeneratingPack(false);
    }
  }

  function handleNext() {
    if (currentIndex >= quizList.length - 1) {
      setIsCompleted(true);
      persistState({
        isCompleted: true,
        completedAt: Date.now(),
        feedback,
        feedbackQuizKey: feedback ? currentQuizKey : ""
      });
      return;
    }
    const nextIndex = currentIndex + 1;
    const nextQuizKey = quizKey(quizList[nextIndex], nextIndex);
    setCurrentIndex(nextIndex);
    setSelectedOption(answers[nextQuizKey] || "");
    setFeedback(null);
    setShowHint(false);
    setError("");
    setIsCompleted(false);
    persistState({ currentIndex: nextIndex, feedback: null, feedbackQuizKey: "", isCompleted: false, completedAt: null });
  }

  function optionClass(key: string) {
    if (!feedback) return selectedOption === key ? "selected" : "";
    if (feedback.correct_option === key) return "correct";
    if (selectedOption === key && !feedback.is_correct) return "wrong";
    return "dimmed";
  }

  if (loading) {
    return (
      <View className="page practice-page">
        <Text className="page-title">刷题</Text>
        <View className="card empty-card">
          <Text>{generatingPack ? "正在生成定向练习题..." : "正在加载练习题..."}</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="page practice-page">
      <View className="practice-header">
        <View>
          <Text className="page-title">刷题</Text>
          <Text className="page-subtitle">当前进度：{progressText}</Text>
        </View>
        <Button className="button-secondary header-button" onClick={() => Taro.switchTab({ url: "/pages/chat/index" })}>
          去问答
        </Button>
      </View>

      {!currentQuiz ? (
        <View className="card empty-card">
          <Text className="empty-title">还没有可练习的题</Text>
          <Text className="empty-desc">可以回到问答页，让助手围绕某个知识点出题。</Text>
          {error ? <Text className="error-text">{error}</Text> : null}
          <Button className="button-secondary action-button" onClick={bootstrapPractice}>
            重新加载
          </Button>
        </View>
      ) : isLegacyQuiz ? (
        <View className="card empty-card">
          <Text className="empty-title">这组题还是旧格式</Text>
          <Text className="empty-desc">当前题包缺少完整 A/B/C/D 单选结构，不能直接提交。可以回问答页重新生成，或用当前题目作为上下文尝试 AI 补题。</Text>
          {error ? <Text className="error-text">{error}</Text> : null}
          <Button className="button-primary action-button" loading={generatingPack} disabled={generatingPack} onClick={handleGenerateMore}>
            {generatingPack ? "正在补题" : "AI 补题"}
          </Button>
          <Button className="button-secondary action-button" onClick={() => Taro.switchTab({ url: "/pages/chat/index" })}>
            回问答页
          </Button>
        </View>
      ) : (
        <View className="card quiz-card">
          <View className="quiz-meta">
            <Text className="pill">{currentQuiz.difficulty || "练习"}</Text>
            <Text className="knowledge-point">{currentQuiz.concept_name || currentQuiz.knowledge_point || "综合"}</Text>
          </View>
          <Text className="question-text">{currentQuiz.question}</Text>
          <View className="source-row">
            <Text className="source-text">{currentQuiz.source_name || (currentQuiz.source_type === "question_bank" ? "题库题" : "AI 补题")}</Text>
            {currentQuiz.source_year ? <Text className="source-text">{currentQuiz.source_year}</Text> : null}
          </View>

          {currentQuiz.hint ? (
            <View className="hint-card">
              <Button className="button-secondary hint-button" onClick={() => setShowHint((value) => !value)}>
                {showHint ? "收起提示" : "查看提示"}
              </Button>
              {showHint ? <Text className="hint-text">{hintText(currentQuiz.hint)}</Text> : null}
            </View>
          ) : null}

          <View className="option-list">
            {currentOptions.map((option) => (
              <View
                key={option.key}
                className={`option-item ${optionClass(option.key)}`}
                onClick={() => selectOption(option.key)}
              >
                <Text className="option-key">{option.key}</Text>
                <View className="option-main">
                  <Text className="option-text">{option.text}</Text>
                  {feedback ? <Text className="option-rationale">{feedback.option_rationales?.[option.key] || ""}</Text> : null}
                </View>
              </View>
            ))}
          </View>

          {feedback ? (
            <View className={`feedback-card ${feedback.is_correct ? "ok" : "bad"}`}>
              <Text className="feedback-title">{feedback.is_correct ? "回答正确" : "再看看这一步"}</Text>
              <View className="answer-grid">
                <View className="answer-panel">
                  <Text className="answer-label">你的答案</Text>
                  <Text className="answer-value">{feedback.selected_option || selectedOption}. {selectedOptionText || "未找到选项文本"}</Text>
                </View>
                <View className="answer-panel correct">
                  <Text className="answer-label">正确答案</Text>
                  <Text className="answer-value">{feedback.correct_option}. {correctOptionText || "未找到选项文本"}</Text>
                </View>
              </View>
              {!feedback.is_correct ? (
                <Text className="feedback-text">{selectedRationale || "你选的这一项需要结合标准解析再看一遍。"}</Text>
              ) : null}
              {!feedback.is_correct ? (
                <Text className="feedback-text">{correctRationale || "正确选项的理由见下面的标准解析。"}</Text>
              ) : null}
              <Text className="feedback-label">标准解析</Text>
              <Text className="feedback-text">{feedback.explanation}</Text>
              {feedback.mastery_evaluation ? (
                <View className="mastery-card">
                  <Text className="feedback-label">掌握度判断</Text>
                  <Text className="mastery-title">{feedback.mastery_evaluation.mastery_level} · {scoreText(feedback.mastery_evaluation.mastery_score)}</Text>
                  <Text className="feedback-text">{feedback.personalized_feedback || feedback.mastery_evaluation.feedback}</Text>
                  <Text className="feedback-text">准确性 {scoreText(feedback.mastery_evaluation.score_breakdown?.accuracy)} · 完整度 {scoreText(feedback.mastery_evaluation.score_breakdown?.completeness)} · 理解深度 {scoreText(feedback.mastery_evaluation.score_breakdown?.understanding_depth)}</Text>
                </View>
              ) : feedback.personalized_feedback ? (
                <Text className="feedback-text">{feedback.personalized_feedback}</Text>
              ) : null}
            </View>
          ) : null}

          {isCompleted ? (
            <View className="complete-card">
              <Text className="complete-title">这组题已完成</Text>
              <Text className="complete-desc">可以继续复盘，也可以点 AI 补题生成新的练习。</Text>
            </View>
          ) : null}

          {error ? <Text className="error-text">{error}</Text> : null}

          {!feedback && !isCompleted ? (
            <Button className="button-primary action-button" disabled={!selectedOption || submitting} loading={submitting} onClick={handleSubmit}>
              提交答案
            </Button>
          ) : feedback ? (
            <View>
              <Button className="button-primary action-button" onClick={handleNext}>
                {currentIndex >= quizList.length - 1 ? "完成复盘" : "下一题"}
              </Button>
              <Button className="button-secondary action-button" loading={generatingPack} disabled={generatingPack} onClick={handleGenerateMore}>
                {generatingPack ? "正在补题" : "AI 补题"}
              </Button>
            </View>
          ) : (
            <Button className="button-secondary action-button" loading={generatingPack} disabled={generatingPack} onClick={handleGenerateMore}>
              {generatingPack ? "正在补题" : "AI 补题"}
            </Button>
          )}
        </View>
      )}
    </View>
  );
}
