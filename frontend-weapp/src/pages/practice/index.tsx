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
  clearStoredQuiz,
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

function completedOptionRationales(quiz: QuizItem) {
  const raw = quiz.option_rationales || {};
  return OPTION_KEYS.reduce<Record<string, string>>((rationales, key) => {
    const rationale = raw[key];
    rationales[key] = rationale || (
      key === quiz.correct_option
        ? `${key} 是正确答案，依据见标准解析。`
        : "该选项不是本题正确答案，需要对照题干条件和标准解析排除。"
    );
    return rationales;
  }, {});
}

function buildImmediateFeedback(quiz: QuizItem, selectedOption: string): PracticeAttemptResult {
  const selected = selectedOption as OptionKey;
  return {
    is_correct: selected === quiz.correct_option,
    selected_option: selected,
    correct_option: quiz.correct_option,
    explanation: quiz.explanation || `正确答案是 ${quiz.correct_option}。请结合题干条件和选项辨析复盘。`,
    option_rationales: completedOptionRationales(quiz),
    memory: {
      weak_points: [],
      error_count: {},
      recent_topics: []
    },
    session_memory: null,
    mastery_evaluation: null,
    personalized_feedback: "已完成判题，学习画像正在后台更新，稍后可在学习中心查看。",
    analysis_status: "queued"
  };
}

function feedbacksWith(
  currentFeedbacks: Record<string, PracticeAttemptResult>,
  key: string,
  nextFeedback: PracticeAttemptResult | null | undefined
) {
  if (!key || !nextFeedback) return currentFeedbacks;
  return {
    ...currentFeedbacks,
    [key]: nextFeedback
  };
}

export default function PracticePage() {
  const [quizList, setQuizList] = useState<QuizItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState("");
  const [feedback, setFeedback] = useState<PracticeAttemptResult | null>(null);
  const [feedbacks, setFeedbacks] = useState<Record<string, PracticeAttemptResult>>({});
  const [sessionId, setSessionId] = useState("");
  const [notebookId, setNotebookId] = useState(getStoredNotebookId());
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [showHint, setShowHint] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);
  const [completedAt, setCompletedAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [generatingPack, setGeneratingPack] = useState(false);
  const [quizClearedManually, setQuizClearedManually] = useState(false);
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
  const isLastQuestion = Boolean(currentQuiz && currentIndex >= quizList.length - 1);
  const showCompletedCard = isCompleted && isLastQuestion;
  const hasPreviousQuestion = currentIndex > 0;
  const hasNextQuestion = currentIndex < quizList.length - 1;
  const navigationDisabled = submitting || generatingPack;
  const progressText = useMemo(() => {
    if (!quizList.length) return "0 / 0";
    return `${currentIndex + 1} / ${quizList.length}`;
  }, [currentIndex, quizList.length]);

  useDidShow(() => {
    void bootstrapPractice();
  });

  async function bootstrapPractice(options: { force?: boolean } = {}) {
    if (quizClearedManually && !options.force) {
      setLoading(false);
      return;
    }
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    setLearningStoreUser(user.id);
    setQuizClearedManually(false);
    await loadQuiz(user.id);
  }

  function persistState(partial: Partial<StoredQuizState> = {}) {
    const nextFeedback = partial.feedback !== undefined ? partial.feedback : feedback;
    const nextFeedbackQuizKey = partial.feedbackQuizKey ?? (nextFeedback ? currentQuizKey : "");
    const nextFeedbacks = partial.feedbacks ?? feedbacksWith(feedbacks, nextFeedbackQuizKey, nextFeedback);
    setStoredQuizState({
      sessionId: partial.sessionId ?? sessionId,
      subjectId: partial.subjectId ?? notebookId,
      items: partial.items ?? quizList,
      currentIndex: partial.currentIndex ?? currentIndex,
      answers: partial.answers ?? answers,
      feedback: nextFeedback ?? null,
      feedbackQuizKey: nextFeedbackQuizKey,
      feedbacks: nextFeedbacks,
      isCompleted: partial.isCompleted ?? isCompleted,
      completedAt: partial.completedAt !== undefined ? partial.completedAt : completedAt
    });
  }

  function hydratePractice(items: QuizItem[], nextSessionId: string, nextNotebookId: string, partial: Partial<StoredQuizState> = {}) {
    const nextIndex = Math.min(partial.currentIndex || 0, Math.max(items.length - 1, 0));
    const nextAnswers = partial.answers || {};
    const nextQuizKey = quizKey(items[nextIndex], nextIndex);
    const nextFeedbacks = feedbacksWith(partial.feedbacks || {}, partial.feedbackQuizKey || "", partial.feedback);
    const nextFeedback = nextFeedbacks[nextQuizKey] || null;
    const nextCompletedAt = partial.completedAt ?? null;
    setQuizList(items);
    setCurrentIndex(nextIndex);
    setSessionId(nextSessionId);
    setNotebookId(nextNotebookId);
    setStoredNotebookId(nextNotebookId);
    setStoredSessionId(nextSessionId);
    setAnswers(nextAnswers);
    setSelectedOption(nextFeedback?.selected_option || nextAnswers[nextQuizKey] || "");
    setFeedback(nextFeedback);
    setFeedbacks(nextFeedbacks);
    setShowHint(false);
    setIsCompleted(Boolean(partial.isCompleted));
    setCompletedAt(nextCompletedAt);
    setStoredQuizState({
      sessionId: nextSessionId,
      subjectId: nextNotebookId,
      items,
      currentIndex: nextIndex,
      answers: nextAnswers,
      feedback: nextFeedback,
      feedbackQuizKey: nextFeedback ? nextQuizKey : "",
      feedbacks: nextFeedbacks,
      isCompleted: Boolean(partial.isCompleted),
      completedAt: nextCompletedAt
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

  async function handleClearQuizLibrary() {
    if (generatingPack || submitting) {
      Taro.showToast({ title: "当前正在处理题目，请稍后再清空", icon: "none" });
      return;
    }
    if (!quizList.length) {
      Taro.showToast({ title: "当前没有可清空的题库", icon: "none" });
      return;
    }

    const result = await Taro.showModal({
      title: "清空题库",
      content: "将清空当前小程序里的题包、作答进度和反馈记录，不会删除后端历史或聊天记录。",
      confirmText: "清空",
      confirmColor: "#ff5a7a",
      cancelText: "取消"
    });
    if (!result.confirm) return;

    const user = requireAuthUser();
    clearStoredQuiz(user?.id);
    setQuizClearedManually(true);
    setQuizList([]);
    setCurrentIndex(0);
    setSelectedOption("");
    setAnswers({});
    setFeedback(null);
    setFeedbacks({});
    setShowHint(false);
    setIsCompleted(false);
    setCompletedAt(null);
    setError("");
    setLoading(false);
    Taro.showToast({ title: "题库已清空", icon: "success" });
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
        feedbacks: cached.feedbacks || {},
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
    const previousSessionId = sessionId;
    const previousNotebookId = notebookId;
    const previousAnswers = answers;
    const previousFeedback = feedback;
    const previousFeedbacks = feedbacks;
    const previousIsCompleted = isCompleted;
    const previousCompletedAt = completedAt;
    const previousStoredState = getStoredQuizState();
    const nextAnswers = {
      ...answers,
      [currentQuizKey]: selectedOption
    };
    const immediateFeedback = buildImmediateFeedback(currentQuiz, selectedOption);
    const nextIsCompleted = isCompleted || currentIndex >= quizList.length - 1;
    const nextCompletedAt = nextIsCompleted ? (completedAt ?? Date.now()) : null;
    const nextFeedbacks = feedbacksWith(feedbacks, currentQuizKey, immediateFeedback);
    setSessionId(nextSessionId);
    setNotebookId(nextNotebookId);
    setFeedback(immediateFeedback);
    setFeedbacks(nextFeedbacks);
    setAnswers(nextAnswers);
    setIsCompleted(nextIsCompleted);
    setCompletedAt(nextCompletedAt);
    setStoredQuizState({
      sessionId: nextSessionId,
      subjectId: nextNotebookId,
      items: quizList,
      currentIndex,
      answers: nextAnswers,
      feedback: immediateFeedback,
      feedbackQuizKey: currentQuizKey,
      feedbacks: nextFeedbacks,
      isCompleted: nextIsCompleted,
      completedAt: nextCompletedAt
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
      const calibratedFeedback: PracticeAttemptResult = {
        ...result,
        selected_option: result.selected_option || (selectedOption as OptionKey),
        explanation: result.explanation || immediateFeedback.explanation,
        option_rationales: result.option_rationales || immediateFeedback.option_rationales,
        personalized_feedback: result.personalized_feedback || immediateFeedback.personalized_feedback
      };
      const calibratedFeedbacks = feedbacksWith(nextFeedbacks, currentQuizKey, calibratedFeedback);
      setFeedback(calibratedFeedback);
      setFeedbacks(calibratedFeedbacks);
      setAnswers(nextAnswers);
      setIsCompleted(nextIsCompleted);
      setCompletedAt(nextCompletedAt);
      setStoredQuizState({
        sessionId: nextSessionId,
        subjectId: nextNotebookId,
        items: quizList,
        currentIndex,
        answers: nextAnswers,
        feedback: calibratedFeedback,
        feedbackQuizKey: currentQuizKey,
        feedbacks: calibratedFeedbacks,
        isCompleted: nextIsCompleted,
        completedAt: nextCompletedAt
      });
    } catch (err: any) {
      setSessionId(previousSessionId);
      setNotebookId(previousNotebookId);
      setAnswers(previousAnswers);
      setFeedback(previousFeedback);
      setFeedbacks(previousFeedbacks);
      setIsCompleted(previousIsCompleted);
      setCompletedAt(previousCompletedAt);
      setStoredQuizState(previousStoredState);
      setError(err?.message ? `保存失败：${err.message}，请重试` : "保存失败，请稍后重试");
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
      const nextFeedbacks = feedbacksWith(feedbacks, currentQuizKey, feedback);
      setQuizList(nextQuizList);
      setCurrentIndex(nextIndex);
      setFeedback(nextFeedback);
      setFeedbacks(nextFeedbacks);
      setSelectedOption(nextSelectedOption);
      setShowHint(false);
      setIsCompleted(false);
      setCompletedAt(null);
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
        feedbacks: nextFeedbacks,
        isCompleted: false,
        completedAt: null
      });
    } catch (err: any) {
      setError(err?.message || "AI 补题失败，请稍后重试");
    } finally {
      setGeneratingPack(false);
    }
  }

  function goToQuestion(targetIndex: number) {
    if (targetIndex < 0 || targetIndex >= quizList.length || navigationDisabled) return;
    const nextFeedbacks = feedbacksWith(feedbacks, currentQuizKey, feedback);
    const nextQuizKey = quizKey(quizList[targetIndex], targetIndex);
    const nextFeedback = nextFeedbacks[nextQuizKey] || null;
    const nextSelectedOption = nextFeedback?.selected_option || answers[nextQuizKey] || "";
    setCurrentIndex(targetIndex);
    setSelectedOption(nextSelectedOption);
    setFeedback(nextFeedback);
    setFeedbacks(nextFeedbacks);
    setShowHint(false);
    setError("");
    setStoredQuizState({
      sessionId,
      subjectId: notebookId,
      items: quizList,
      currentIndex: targetIndex,
      answers,
      feedback: nextFeedback,
      feedbackQuizKey: nextFeedback ? nextQuizKey : "",
      feedbacks: nextFeedbacks,
      isCompleted,
      completedAt
    });
  }

  function handleNext() {
    if (navigationDisabled) return;
    if (currentIndex >= quizList.length - 1) {
      const nextCompletedAt = completedAt ?? Date.now();
      setIsCompleted(true);
      setCompletedAt(nextCompletedAt);
      persistState({
        isCompleted: true,
        completedAt: nextCompletedAt,
        feedback,
        feedbackQuizKey: feedback ? currentQuizKey : "",
        feedbacks: feedbacksWith(feedbacks, currentQuizKey, feedback)
      });
      return;
    }
    goToQuestion(currentIndex + 1);
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
        <View className="practice-header-main">
          <Text className="page-title">刷题</Text>
          <Text className="page-subtitle">当前进度：{progressText}</Text>
        </View>
        <View className="practice-header-actions">
          <Button className="button-secondary header-button" onClick={() => Taro.switchTab({ url: "/pages/chat/index" })}>
            去问答
          </Button>
          <Button
            className="button-secondary header-button clear-header-button"
            disabled={submitting || generatingPack || !quizList.length}
            onClick={handleClearQuizLibrary}
          >
            清空题库
          </Button>
        </View>
      </View>

      {!currentQuiz ? (
        <View className="card empty-card">
          <Text className="empty-title">还没有可练习的题</Text>
          <Text className="empty-desc">可以回到问答页，让助手围绕某个知识点出题。</Text>
          {error ? <Text className="error-text">{error}</Text> : null}
          <Button className="button-secondary action-button" onClick={() => void bootstrapPractice({ force: true })}>
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

          {showCompletedCard ? (
            <View className="complete-card">
              <Text className="complete-title">这组题已完成</Text>
              <Text className="complete-desc">可以继续复盘，也可以点 AI 补题生成新的练习。</Text>
            </View>
          ) : null}

          {error ? <Text className="error-text">{error}</Text> : null}

          <View className="question-nav-row">
            <Button
              className="button-secondary question-nav-button"
              disabled={!hasPreviousQuestion || navigationDisabled}
              onClick={() => goToQuestion(currentIndex - 1)}
            >
              上一题
            </Button>
            <Text className="question-nav-count">第 {currentIndex + 1} / 共 {quizList.length} 题</Text>
            <Button
              className="button-secondary question-nav-button"
              disabled={!hasNextQuestion || navigationDisabled}
              onClick={() => goToQuestion(currentIndex + 1)}
            >
              下一题
            </Button>
          </View>

          {!feedback ? (
            <Button className="button-primary action-button" disabled={!selectedOption || submitting || generatingPack} loading={submitting} onClick={handleSubmit}>
              提交答案
            </Button>
          ) : (
            <View>
              <Button className="button-primary action-button" loading={submitting} disabled={submitting || generatingPack} onClick={handleNext}>
                {submitting ? "正在保存" : isLastQuestion ? "完成复盘" : "下一题"}
              </Button>
              <Button className="button-secondary action-button" loading={generatingPack} disabled={generatingPack || submitting} onClick={handleGenerateMore}>
                {generatingPack ? "正在补题" : "AI 补题"}
              </Button>
            </View>
          )}
        </View>
      )}
    </View>
  );
}
