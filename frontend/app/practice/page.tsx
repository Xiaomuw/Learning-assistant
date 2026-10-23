"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpenCheck,
  CheckCircle2,
  Lightbulb,
  HelpCircle,
  PencilRuler,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react";
import BottomNav from "@/components/BottomNav";
import { useAuth } from "@/components/AuthProvider";
import {
  createPracticePack,
  fetchLatestQuizBundle,
  submitPracticeAttempt,
  type MasteryEvaluationResult,
  type QuizItem,
  type AuthUser,
} from "@/lib/api";
import {
  appendStoredQuiz,
  DEFAULT_NOTEBOOK_ID,
  buildQuizSignature,
  clearStoredPracticeState,
  clearStoredQuiz,
  getQuizItemNotebookId,
  loadStoredMemory,
  loadStoredPracticeState,
  loadStoredQuiz,
  loadStoredQuizMeta,
  persistMemory,
  persistPracticeState,
  persistQuiz,
  setLearningStoreUser,
  type StoredPracticeState,
} from "@/lib/learning-store";

type OptionKey = "A" | "B" | "C" | "D";

interface AttemptFeedback {
  isCorrect: boolean;
  submittedOption?: OptionKey;
  correctOption: OptionKey;
  explanation: string;
  optionRationales: Record<string, string>;
  masteryEvaluation?: MasteryEvaluationResult | null;
  personalizedFeedback?: string;
}

interface LearningCenterPracticeTarget {
  subjectId: string;
  conceptId: string;
  conceptName: string;
}

function practicePackFailureMessage(result: {
  quiz_request?: { need_clarification?: boolean } | null;
  quiz_clarification?: unknown;
  generation_status?: Record<string, unknown>;
  message?: string;
}) {
  if (result.quiz_clarification || result.quiz_request?.need_clarification) {
    return "还需要先确认练习方向，请回问答页输入具体知识点。";
  }

  if (typeof result.message === "string" && result.message.trim()) {
    return result.message.trim();
  }

  const status = result.generation_status ?? {};
  const degradedReason =
    typeof status.degraded_reason === "string" ? status.degraded_reason.trim() : "";
  if (status.empty_generation || status.ai_generation_failed || degradedReason) {
    return degradedReason
      ? `已识别练习方向，但题目生成失败：${degradedReason}`
      : "已识别练习方向，但题目生成失败，请稍后重试。";
  }

  return "AI 补题暂时没有生成题目，请稍后重试。";
}

function safePracticeHint(hint: string | undefined) {
  const raw = (hint ?? "").trim();
  if (!raw) {
    return "";
  }
  const cleaned = raw
    .replace(/正确答案是\s*[A-D]/gi, "")
    .replace(/选择\s*[A-D]\s*(?:并|，|,|。|\.)?/gi, "")
    .replace(/答案\s*[A-D]/gi, "")
    .trim();
  return cleaned || "先根据题干关键条件排除明显不符合的选项，再提交作答。";
}

function countQuizSignatureItems(signature: string | undefined) {
  if (!signature) {
    return 0;
  }
  return signature.split("|").filter(Boolean).length;
}

function usablePracticeTopic(value: string | undefined) {
  const topic = value?.trim();
  if (!topic || topic === "混合练习") {
    return "";
  }
  return topic;
}

function parseLearningCenterPracticeTarget(): LearningCenterPracticeTarget | null {
  if (typeof window === "undefined") {
    return null;
  }

  const params = new URLSearchParams(window.location.search);
  const conceptId = params.get("concept")?.trim() || "";
  if (!conceptId) {
    return null;
  }

  const conceptName = params.get("concept_name")?.trim() || conceptId;
  return {
    subjectId: params.get("subject")?.trim() || DEFAULT_NOTEBOOK_ID,
    conceptId,
    conceptName,
  };
}

function restorePracticeSnapshot(nextQuizList: QuizItem[], fallbackSessionId = "", fallbackNotebookId = DEFAULT_NOTEBOOK_ID) {
  const state = {
    currentIndex: 0, selectedOption: null as OptionKey | null,
    feedback: null as AttemptFeedback | null, showHint: false,
    currentSessionId: fallbackSessionId, currentNotebookId: fallbackNotebookId,
    isPracticeCompleted: false, practiceCompletedAt: null as number | null,
  };

  if (nextQuizList.length === 0) {
    state.currentIndex = 0;
    state.selectedOption = null;
    state.feedback = null;
    state.showHint = false;
    state.currentSessionId = fallbackSessionId;
    state.currentNotebookId = fallbackNotebookId || DEFAULT_NOTEBOOK_ID;
    state.isPracticeCompleted = false;
    state.practiceCompletedAt = null;

    return state;
  }

  const quizSignature = buildQuizSignature(nextQuizList);
  const quizMeta = loadStoredQuizMeta();
  const storedState = loadStoredPracticeState();
  const metaTopic = quizMeta?.topic?.trim() || "";
  const stateTopic = storedState?.topic?.trim() || "";
  const metaSubjectId = quizMeta?.subjectId || fallbackNotebookId || DEFAULT_NOTEBOOK_ID;
  const stateSubjectId = storedState?.subjectId || storedState?.notebookId || DEFAULT_NOTEBOOK_ID;
  const metaTopics = quizMeta?.topics || (metaTopic ? [metaTopic] : []);
  const metaSubjectIds = quizMeta?.subjectIds || (metaSubjectId ? [metaSubjectId] : []);
  const metaSessionIds = quizMeta?.sessionIds || (quizMeta?.sessionId ? [quizMeta.sessionId] : []);
  const metaMatchesState =
    !storedState ||
    ((!metaTopic ||
      !stateTopic ||
      metaTopic === stateTopic ||
      metaTopic === "混合练习" ||
      metaTopics.includes(stateTopic)) &&
      (!metaSubjectId ||
        !stateSubjectId ||
        metaSubjectId === stateSubjectId ||
        metaSubjectIds.includes(stateSubjectId)) &&
      (!storedState.sessionId ||
        !quizMeta?.sessionId ||
        storedState.sessionId === quizMeta.sessionId ||
        metaSessionIds.includes(storedState.sessionId)));
  const restoredQuizItemCount =
    storedState?.quizItemCount || countQuizSignatureItems(storedState?.quizSignature);
  const appendedToStoredQuiz = Boolean(
    storedState &&
      restoredQuizItemCount > 0 &&
      restoredQuizItemCount < nextQuizList.length &&
      buildQuizSignature(nextQuizList.slice(0, restoredQuizItemCount)) === storedState.quizSignature
  );
  if (
    storedState &&
    ((storedState.quizSignature === quizSignature && metaMatchesState) ||
      (appendedToStoredQuiz && metaMatchesState))
  ) {
    const shouldJumpToAppendedItems = Boolean(
      appendedToStoredQuiz &&
        storedState.isCompleted &&
        restoredQuizItemCount < nextQuizList.length
    );
    const restoredIndex = Math.max(
      0,
      Math.min(
        shouldJumpToAppendedItems ? restoredQuizItemCount : storedState.currentIndex,
        nextQuizList.length - 1
      )
    );
    state.currentIndex = restoredIndex;
    state.selectedOption = shouldJumpToAppendedItems ? null : storedState.selectedOption;
    state.feedback = shouldJumpToAppendedItems ? null : storedState.feedback;
    state.showHint = shouldJumpToAppendedItems ? false : storedState.showHint;
    state.currentSessionId = storedState.sessionId || quizMeta?.sessionId || fallbackSessionId;
    state.currentNotebookId =
      getQuizItemNotebookId(
        nextQuizList[restoredIndex],
        storedState.notebookId || quizMeta?.subjectId || fallbackNotebookId || DEFAULT_NOTEBOOK_ID
      )
    ;
    state.isPracticeCompleted = shouldJumpToAppendedItems ? false : Boolean(storedState.isCompleted);
    state.practiceCompletedAt = shouldJumpToAppendedItems ? null : storedState.completedAt ?? null;
  } else {
    state.currentIndex = 0;
    state.selectedOption = null;
    state.feedback = null;
    state.showHint = false;
    state.currentSessionId = quizMeta?.sessionId || fallbackSessionId;
    state.currentNotebookId = getQuizItemNotebookId(nextQuizList[0], quizMeta?.subjectId || fallbackNotebookId || DEFAULT_NOTEBOOK_ID);
    state.isPracticeCompleted = false;
    state.practiceCompletedAt = null;
  }


  return state;
}

export default function PracticePage() {
  const { user, isLoading } = useAuth();
  if (isLoading || !user) return <p role="status">正在加载练习...</p>;
  return <PracticeSession key={user.id} user={user} />;
}

function PracticeSession({ user }: { user: AuthUser }) {
  const router = useRouter();
  const isLoading = false;
  const [initial] = useState(() => {
    const quiz = loadStoredQuiz();
    return { quiz, ...restorePracticeSnapshot(quiz) };
  });
  const hasLoadedPracticeStateRef = useRef(initial.quiz.length > 0);
  const [quizList, setQuizList] = useState<QuizItem[]>(initial.quiz);
  const [currentIndex, setCurrentIndex] = useState(initial.currentIndex);
  const [selectedOption, setSelectedOption] = useState<OptionKey | null>(initial.selectedOption);
  const [showHint, setShowHint] = useState(initial.showHint);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingPack, setIsGeneratingPack] = useState(false);
  const [feedback, setFeedback] = useState<AttemptFeedback | null>(initial.feedback);
  const [submitError, setSubmitError] = useState("");
  const [packError, setPackError] = useState("");
  const [currentSessionId, setCurrentSessionId] = useState(initial.currentSessionId);
  const [currentNotebookId, setCurrentNotebookId] = useState(initial.currentNotebookId);
  const [learningCenterTarget] =
    useState<LearningCenterPracticeTarget | null>(parseLearningCenterPracticeTarget);
  const [isPracticeCompleted, setIsPracticeCompleted] = useState(initial.isPracticeCompleted);
  const [practiceCompletedAt, setPracticeCompletedAt] = useState<number | null>(initial.practiceCompletedAt);
  const [isClearConfirmOpen, setIsClearConfirmOpen] = useState(false);
  const submitInFlightRef = useRef(false);


  useEffect(() => {
    if (initial.quiz.length > 0) return;
    let active = true;
    void fetchLatestQuizBundle(user.id)
      .then((remoteBundle) => {
        if (!active) return;
        const restored = restorePracticeSnapshot(remoteBundle.quizItems, remoteBundle.sessionId, remoteBundle.notebookId);
        setQuizList(remoteBundle.quizItems);
        setCurrentIndex(restored.currentIndex);
        setSelectedOption(restored.selectedOption);
        setShowHint(restored.showHint);
        setFeedback(restored.feedback);
        setCurrentSessionId(restored.currentSessionId);
        setCurrentNotebookId(restored.currentNotebookId);
        setIsPracticeCompleted(restored.isPracticeCompleted);
        setPracticeCompletedAt(restored.practiceCompletedAt);
        hasLoadedPracticeStateRef.current = true;
        if (remoteBundle.quizItems.length > 0) {
          persistQuiz(remoteBundle.quizItems, {
            topic: remoteBundle.quizItems[0]?.knowledge_point,
            subjectId: remoteBundle.notebookId, sessionId: remoteBundle.sessionId,
          });
        }
      })
      .catch((error) => {
        if (!active) return;
        console.error("加载最新题包失败:", error);
        hasLoadedPracticeStateRef.current = true;
      });
    return () => { active = false; };
  }, [initial.quiz.length, user.id]);

  useEffect(() => {
    if (isLoading || !user || !hasLoadedPracticeStateRef.current || quizList.length === 0) {
      return;
    }

    persistPracticeState({
      quizSignature: buildQuizSignature(quizList),
      quizItemCount: quizList.length,
      currentIndex,
      selectedOption,
      showHint,
      feedback,
      sessionId: currentSessionId,
      notebookId: getQuizItemNotebookId(quizList[currentIndex], currentNotebookId),
      subjectId: getQuizItemNotebookId(quizList[currentIndex], currentNotebookId),
      topic:
        usablePracticeTopic(quizList[currentIndex]?.knowledge_point) ||
        usablePracticeTopic(loadStoredQuizMeta()?.topic),
      isCompleted: isPracticeCompleted,
      completedAt: practiceCompletedAt,
      updatedAt: Date.now(),
    });
  }, [
    currentIndex,
    currentNotebookId,
    currentSessionId,
    feedback,
    isLoading,
    quizList,
    isPracticeCompleted,
    practiceCompletedAt,
    selectedOption,
    showHint,
    user,
  ]);

  const currentQuiz = quizList[currentIndex] ?? null;
  const currentQuizNotebookId = getQuizItemNotebookId(currentQuiz, currentNotebookId);
  const isLastQuestion = currentIndex >= quizList.length - 1;
  const progressPercent =
    quizList.length > 0 ? Math.round(((currentIndex + 1) / quizList.length) * 100) : 0;
  const knowledgePoints = Array.from(
    new Set(quizList.map((item) => item.knowledge_point))
  ).slice(0, 3);
  const currentOptions = currentQuiz?.options ?? [];
  const isLegacyQuiz = Boolean(
    currentQuiz && (!Array.isArray(currentQuiz.options) || currentQuiz.options.length !== 4)
  );
  const sourceLabel = useMemo(() => {
    if (!currentQuiz) {
      return "";
    }
    if (currentQuiz.source_type === "question_bank" && currentQuiz.source_name) {
      return currentQuiz.source_year
        ? `${currentQuiz.source_name} · ${currentQuiz.source_year}`
        : currentQuiz.source_name;
    }
    return "AI 补题";
  }, [currentQuiz]);
  const selectedOptionText =
    currentOptions.find((option) => option.key === (feedback?.submittedOption ?? selectedOption))?.text ?? "";
  const correctOptionText = feedback
    ? currentOptions.find((option) => option.key === feedback.correctOption)?.text ?? ""
    : "";
  const selectedRationale =
    feedback && (feedback.submittedOption ?? selectedOption)
      ? feedback.optionRationales[feedback.submittedOption ?? selectedOption ?? "A"]?.trim() ?? ""
      : "";
  const correctRationale = feedback
    ? feedback.optionRationales[feedback.correctOption]?.trim() ?? ""
    : "";
  const feedbackHero = feedback
    ? feedback.isCorrect
      ? {
          title: "答对了，关键点抓得很稳",
          subtitle: "这题已经掌握住主干了，下面的解析可以帮你把判断理由再压实一遍。",
          badge: "Nice Work",
          icon: <Sparkles size={20} strokeWidth={2.8} />,
          tone: "bg-[#B8F7C1]",
        }
      : {
          title: "这题值得复盘一下",
          subtitle: "别急着跳下一题，先看你选的那一项为什么会误导，再看正确选项的关键依据。",
          badge: "Review",
          icon: <XCircle size={20} strokeWidth={2.8} />,
          tone: "bg-neo-accent",
        }
    : null;
  const masteryLevelLabel = feedback?.masteryEvaluation
    ? {
        mastered: "已掌握",
        learning: "学习中",
        weak: "薄弱点",
      }[feedback.masteryEvaluation.mastery_level]
    : "";
  const isCompletedReview = Boolean(isPracticeCompleted && feedback && isLastQuestion);

  function persistCurrentPracticeState(
    overrides: Partial<Pick<StoredPracticeState, "isCompleted" | "completedAt">> = {}
  ) {
    if (quizList.length === 0) {
      return;
    }

    persistPracticeState({
      quizSignature: buildQuizSignature(quizList),
      quizItemCount: quizList.length,
      currentIndex,
      selectedOption,
      showHint,
      feedback,
      sessionId: currentSessionId,
      notebookId: currentQuizNotebookId,
      subjectId: currentQuizNotebookId,
      topic:
        usablePracticeTopic(currentQuiz?.knowledge_point) ||
        usablePracticeTopic(loadStoredQuizMeta()?.topic),
      isCompleted: isPracticeCompleted,
      completedAt: practiceCompletedAt,
      ...overrides,
      updatedAt: Date.now(),
    });
  }

  function markPracticeCompleted() {
    const nextCompletedAt = practiceCompletedAt ?? Date.now();
    setIsPracticeCompleted(true);
    setPracticeCompletedAt(nextCompletedAt);
    persistCurrentPracticeState({
      isCompleted: true,
      completedAt: nextCompletedAt,
    });
  }

  async function handleSubmit() {
    if (
      !user ||
      !currentQuiz ||
      !selectedOption ||
      feedback ||
      isSubmitting ||
      submitInFlightRef.current
    ) {
      return;
    }

    submitInFlightRef.current = true;
    setSubmitError("");
    setIsSubmitting(true);
    try {
      const submittedOption = selectedOption;
      const submissionSessionId = currentQuiz.source_session_id || currentSessionId;
      const quizItemPayload = { ...currentQuiz };
      delete quizItemPayload.source_session_id;
      const result = await submitPracticeAttempt({
        user_id: user.id,
        session_id: submissionSessionId,
        subject_id: currentQuizNotebookId,
        quiz_item: quizItemPayload,
        selected_option: submittedOption,
      });

      const nextFeedback: AttemptFeedback = {
        submittedOption: result.selected_option ?? submittedOption,
        isCorrect:
          (result.selected_option ?? submittedOption) === result.correct_option &&
          result.is_correct,
        correctOption: result.correct_option,
        explanation: result.explanation,
        optionRationales: result.option_rationales,
        masteryEvaluation: result.mastery_evaluation,
        personalizedFeedback: result.personalized_feedback,
      };
      const nextCompletedAt = isLastQuestion ? Date.now() : null;

      setFeedback(nextFeedback);
      setIsPracticeCompleted(isLastQuestion);
      setPracticeCompletedAt(nextCompletedAt);
      persistPracticeState({
        quizSignature: buildQuizSignature(quizList),
        quizItemCount: quizList.length,
        currentIndex,
        selectedOption: submittedOption,
        showHint,
        feedback: nextFeedback,
        sessionId: submissionSessionId,
        notebookId: currentQuizNotebookId,
        subjectId: currentQuizNotebookId,
        topic:
          usablePracticeTopic(currentQuiz?.knowledge_point) ||
          usablePracticeTopic(loadStoredQuizMeta()?.topic),
        isCompleted: isLastQuestion,
        completedAt: nextCompletedAt,
        updatedAt: Date.now(),
      });
      persistMemory(result.memory);
    } catch (error) {
      console.error("提交作答失败:", error);
      setSubmitError(
        error instanceof Error && error.message
          ? error.message
          : "提交作答失败，请稍后重试。"
      );
    } finally {
      submitInFlightRef.current = false;
      setIsSubmitting(false);
    }
  }

  function resetPracticeView() {
    setQuizList([]);
    setCurrentIndex(0);
    setSelectedOption(null);
    setShowHint(false);
    setFeedback(null);
    setSubmitError("");
    setPackError("");
    setCurrentSessionId("");
    setCurrentNotebookId(DEFAULT_NOTEBOOK_ID);
    setIsPracticeCompleted(false);
    setPracticeCompletedAt(null);
    hasLoadedPracticeStateRef.current = true;
  }

  function handleConfirmClearPracticePack() {
    setLearningStoreUser(user?.id ?? null);
    clearStoredQuiz();
    clearStoredPracticeState();
    resetPracticeView();
    setIsClearConfirmOpen(false);
  }

  async function handleGenerateLearningCenterPack() {
    if (!user || !learningCenterTarget || isGeneratingPack) {
      return;
    }

    setPackError("");
    setSubmitError("");
    setIsGeneratingPack(true);
    try {
      const result = await createPracticePack({
        user_id: user.id,
        session_id: currentSessionId,
        subject_id: learningCenterTarget.subjectId,
        request_text: `针对「${learningCenterTarget.conceptName}」生成 5 道 408 风格单选题`,
        current_practice_question: currentQuiz,
        last_practice_pack: quizList,
        context: {
          concept_id: learningCenterTarget.conceptId,
          concept_name: learningCenterTarget.conceptName,
          active_topic: learningCenterTarget.conceptName,
          topic: learningCenterTarget.conceptName,
        },
      });

      if (Array.isArray(result.items) && result.items.length > 0) {
        const subjectId = result.subject_id || learningCenterTarget.subjectId;
        const nextQuizList = result.items.map((item) => ({
          ...item,
          subject_id: item.subject_id || subjectId,
          notebook_id: item.notebook_id || subjectId,
          knowledge_point: item.knowledge_point || learningCenterTarget.conceptName,
          concept_id: item.concept_id || learningCenterTarget.conceptId,
          concept_name: item.concept_name || learningCenterTarget.conceptName,
        }));
        setLearningStoreUser(user.id);
        clearStoredPracticeState();
        persistQuiz(nextQuizList, {
          topic: learningCenterTarget.conceptName,
          topics: [learningCenterTarget.conceptName],
          subjectId,
          sessionId: currentSessionId,
          shouldSwitchTopic: true,
        });
        setQuizList(nextQuizList);
        setCurrentIndex(0);
        setSelectedOption(null);
        setFeedback(null);
        setShowHint(false);
        setSubmitError("");
        setCurrentNotebookId(subjectId);
        setIsPracticeCompleted(false);
        setPracticeCompletedAt(null);
        hasLoadedPracticeStateRef.current = true;
      } else {
        setPackError(practicePackFailureMessage(result));
      }
    } catch (error) {
      console.error("学习中心定向出题失败:", error);
      setPackError(
        error instanceof Error && error.message
          ? error.message
          : "定向出题失败，请稍后重试。"
      );
    } finally {
      setIsGeneratingPack(false);
    }
  }

  async function handleGenerateMore() {
    if (!user || !currentQuiz || isGeneratingPack || isSubmitting) {
      return;
    }

    setPackError("");
    setSubmitError("");
    setIsGeneratingPack(true);
    try {
      const quizMeta = loadStoredQuizMeta();
      const practiceState = loadStoredPracticeState();
      const memory = loadStoredMemory();
      const topic =
        usablePracticeTopic(currentQuiz.knowledge_point) ||
        usablePracticeTopic(practiceState?.topic) ||
        usablePracticeTopic(quizMeta?.topic) ||
        knowledgePoints[0]?.trim() ||
        "";
      const currentPracticeQuestion =
        topic && !currentQuiz.knowledge_point?.trim()
          ? { ...currentQuiz, knowledge_point: topic }
          : currentQuiz;
      const activeNotebookId = getQuizItemNotebookId(currentQuiz, currentNotebookId);
      const result = await createPracticePack({
        user_id: user.id,
        session_id: currentSessionId,
        subject_id: activeNotebookId,
        request_text: "AI补题",
        current_practice_question: currentPracticeQuestion,
        last_practice_pack: quizList,
        context: {
          topic,
          active_topic: topic,
          last_topic: topic,
          current_question_topic: topic,
          recent_topics: memory.recent_topics,
          weak_points: memory.weak_points,
        },
      });
      if (Array.isArray(result.items) && result.items.length > 0) {
        setLearningStoreUser(user.id);
        const nextQuizList = appendStoredQuiz(result.items, {
          topic:
            result.quiz_request.active_topic ||
            result.quiz_request.topic ||
            result.items[0]?.knowledge_point,
          subjectId: result.quiz_request.subject_id || activeNotebookId,
          sessionId: currentSessionId,
          shouldSwitchTopic: true,
        });
        if (nextQuizList.length <= quizList.length) {
          setPackError("这次没有生成新的题，请稍后再试一次。");
          return;
        }
        const shouldJumpToNewItems = isPracticeCompleted || isLastQuestion;
        const nextIndex = shouldJumpToNewItems
          ? Math.min(quizList.length, Math.max(0, nextQuizList.length - 1))
          : currentIndex;
        setQuizList(nextQuizList);
        setCurrentIndex(nextIndex);
        setCurrentNotebookId(getQuizItemNotebookId(nextQuizList[nextIndex], activeNotebookId));
        setSelectedOption(shouldJumpToNewItems ? null : selectedOption);
        setFeedback(shouldJumpToNewItems ? null : feedback);
        setShowHint(false);
        setIsPracticeCompleted(false);
        setPracticeCompletedAt(null);
      } else {
        setPackError(practicePackFailureMessage(result));
      }
    } catch (error) {
      console.error("AI 补题失败:", error);
      setPackError(
        error instanceof Error && error.message ? error.message : "AI 补题失败，请稍后重试。"
      );
    } finally {
      setIsGeneratingPack(false);
    }
  }

  function handleNext() {
    if (isLastQuestion) {
      markPracticeCompleted();
      return;
    }

    setCurrentIndex((previous) => previous + 1);
    setSelectedOption(null);
    setFeedback(null);
    setShowHint(false);
    setIsPracticeCompleted(false);
    setPracticeCompletedAt(null);
    setSubmitError("");
  }

  function getOptionCardClass(optionKey: OptionKey) {
    const base =
      "relative overflow-hidden rounded-2xl sm:rounded-[1.25rem] border-2 sm:border-[3px] border-neo-ink px-3 py-3 sm:px-4 sm:py-4 shadow-neo-xs sm:shadow-neo-sm";

    if (!feedback) {
      return selectedOption === optionKey
        ? `${base} bg-neo-secondary`
        : `${base} bg-white`;
    }

    if (optionKey === feedback.correctOption) {
      return `${base} bg-[#B8F7C1]`;
    }

    if (optionKey === (feedback.submittedOption ?? selectedOption) && !feedback.isCorrect) {
      return `${base} bg-neo-accent`;
    }

    return `${base} bg-white opacity-75`;
  }

  function getOptionStatusLabel(optionKey: OptionKey) {
    if (!feedback && selectedOption === optionKey) {
      return "已选择";
    }
    if (!feedback) {
      return "";
    }
    if (optionKey === feedback.correctOption) {
      return "正确答案";
    }
    if (optionKey === (feedback.submittedOption ?? selectedOption) && !feedback.isCorrect) {
      return "你的选择";
    }
    return "干扰项";
  }

  if (isLoading || !user) {
    const message = isLoading
      ? "正在恢复你的练习空间…"
      : "登录状态需要刷新，正在带你回到登录页。";

    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-3 sm:px-4">
        <div className="neo-card-secondary w-full p-4 sm:p-5 text-center animate-fade-in">
          <p className="neo-label">Practice</p>
          <p className="mt-2 sm:mt-3 text-base sm:text-lg font-black">{message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-accent px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="neo-label">Practice Mode</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight">选择题练习</h1>
          </div>

          <div className="neo-badge -rotate-3 bg-white">
            {quizList.length > 0 ? `${currentIndex + 1}/${quizList.length}` : "EMPTY"}
          </div>
        </div>
        {quizList.length > 0 ? (
          <div className="mt-4 rounded-full border-[3px] border-neo-ink bg-white p-1 shadow-neo-sm">
            <div
              className="h-3 rounded-full border-r-[3px] border-neo-ink bg-neo-secondary transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        ) : null}
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        {learningCenterTarget ? (
          <section className="neo-card-secondary mb-4 p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-[3px] border-neo-ink bg-white shadow-neo-sm">
                <Target size={18} strokeWidth={2.8} />
              </span>
              <div className="min-w-0 flex-1">
                <p className="neo-label">Learning Center Target</p>
                <h2 className="mt-1 break-words text-xl font-black">
                  {learningCenterTarget.conceptName}
                </h2>
                <p className="mt-2 break-words text-sm font-bold leading-relaxed">
                  来自学习中心的定向练习。点击后才会生成题，不会在页面加载时自动调用。
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={handleGenerateLearningCenterPack}
              disabled={isGeneratingPack}
              className="neo-button mt-4 w-full justify-center disabled:opacity-70"
            >
              <Sparkles size={16} strokeWidth={2.8} />
              {isGeneratingPack ? "正在生成题" : "针对该知识点生成题"}
            </button>
            {packError ? (
              <p className="mt-3 break-words text-sm font-black text-red-700">
                {packError}
              </p>
            ) : null}
          </section>
        ) : null}

        {quizList.length === 0 ? (
          <section className="neo-card-secondary animate-stamp-in p-5">
            <p className="neo-label">No Quiz Yet</p>
            <h2 className="mt-2 text-4xl font-black leading-none">
              题包还是空的
            </h2>
            <p className="mt-4 text-sm font-bold leading-relaxed">
              这组题可能已经做完，或者当前还没有可练习的题包。你可以回问答页让学习助手出题，也可以去“我的”页领取推荐真题。
            </p>
            <div className="mt-5 flex flex-col gap-3">
              <Link href="/chat" className="neo-button w-full justify-center">
                去问答页生成练习题
                <ArrowRight size={16} strokeWidth={2.8} />
              </Link>
              <Link href="/profile" className="neo-button-secondary w-full justify-center">
                去我的页看推荐题
                <ArrowRight size={16} strokeWidth={2.8} />
              </Link>
            </div>
          </section>
        ) : isLegacyQuiz ? (
          <section className="neo-card-secondary animate-stamp-in p-5">
            <p className="neo-label">Legacy Quiz</p>
            <h2 className="mt-2 text-4xl font-black leading-none">
              这组题还是旧格式
            </h2>
            <p className="mt-4 text-sm font-bold leading-relaxed">
              当前题包还是老的开放题结构，不能直接进入新的单选题流程。回问答页重新生成一组题，或者去“我的”页看新的推荐题。
            </p>
            <div className="mt-5 flex flex-col gap-3">
              <Link href="/chat" className="neo-button w-full justify-center">
                回问答页重新生成
                <ArrowRight size={16} strokeWidth={2.8} />
              </Link>
              <Link href="/profile" className="neo-button-secondary w-full justify-center">
                去我的页找推荐题
                <ArrowRight size={16} strokeWidth={2.8} />
              </Link>
            </div>
          </section>
        ) : (
          <div className="space-y-4">
            <section className="neo-card-muted p-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <PencilRuler size={16} strokeWidth={2.8} />
                    <p className="neo-label">Practice Pack</p>
                  </div>
                  <h2 className="mt-2 text-2xl font-black">
                    第 {currentIndex + 1} 题 / 共 {quizList.length} 题
                  </h2>
                </div>
                <span className="neo-badge bg-white">{progressPercent}%</span>
              </div>

              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <button
                  type="button"
                  onClick={handleGenerateMore}
                  disabled={isGeneratingPack || isSubmitting}
                  className="neo-button-secondary w-full justify-center disabled:opacity-70"
                >
                  <Sparkles size={16} strokeWidth={2.8} />
                  {isGeneratingPack ? "正在补题" : "AI 补题"}
                </button>
                <button
                  type="button"
                  onClick={() => setIsClearConfirmOpen(true)}
                  disabled={isSubmitting || isGeneratingPack}
                  aria-label="清空当前练习题库"
                  className="neo-button-secondary w-full justify-center bg-neo-accent disabled:opacity-70"
                >
                  <XCircle size={16} strokeWidth={2.8} />
                  清空题库
                </button>
              </div>
              {packError ? (
                <p className="mt-3 text-sm font-black text-red-700">{packError}</p>
              ) : null}

              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                  <p className="neo-label">知识点</p>
                  <p className="mt-1 text-sm font-black">
                    {currentQuiz?.knowledge_point ?? "综合"}
                  </p>
                </div>
                <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                  <p className="neo-label">题源</p>
                  <p className="mt-1 text-sm font-black">{sourceLabel || "练习题包"}</p>
                </div>
                <div className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                  <p className="neo-label">节奏</p>
                  <p className="mt-1 text-sm font-black">
                    {feedback ? "已判题，可看解析" : selectedOption ? "已选，准备提交" : "先选一项"}
                  </p>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap gap-2">
                {knowledgePoints.map((point) => (
                  <span key={point} className="neo-badge bg-white">
                    <Target size={12} strokeWidth={2.8} />
                    {point}
                  </span>
                ))}
              </div>
            </section>

            {isCompletedReview ? (
              <section className="rounded-[1.5rem] border-[3px] border-neo-ink bg-[#B8F7C1] p-4 shadow-neo">
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border-[3px] border-neo-ink bg-white shadow-neo-sm">
                    <CheckCircle2 size={18} strokeWidth={2.8} />
                  </span>
                  <div>
                    <p className="neo-label">Practice Complete</p>
                    <h3 className="mt-1 text-xl font-black">这组题已完成</h3>
                    <p className="mt-2 text-sm font-bold leading-relaxed">
                      我已经保留了你的作答和解析。你可以继续复盘这组题，或者点 AI 补题生成新的练习。
                    </p>
                  </div>
                </div>
              </section>
            ) : null}

            <section className="neo-card animate-stamp-in bg-white p-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="neo-badge bg-neo-accent">
                  {currentQuiz?.difficulty ?? "基础"}
                </span>
                <span className="neo-badge bg-neo-secondary">
                  {currentQuiz?.knowledge_point ?? "综合"}
                </span>
                {sourceLabel ? (
                  <span className="neo-badge bg-white">{sourceLabel}</span>
                ) : null}
              </div>

              <p className="mt-4 text-xl font-black leading-snug whitespace-pre-wrap">
                {currentQuiz?.question ?? ""}
              </p>

              {currentQuiz?.hint ? (
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => setShowHint((value) => !value)}
                    className="neo-button-ghost w-full justify-center"
                  >
                    <HelpCircle size={16} strokeWidth={2.8} />
                    {showHint ? "收起提示" : "查看提示"}
                  </button>

                  {showHint ? (
                    <div className="neo-card-secondary mt-3 p-4">
                      <p className="neo-label">Hint</p>
                      <p className="mt-2 text-sm font-bold leading-relaxed">
                        {safePracticeHint(currentQuiz.hint)}
                      </p>
                    </div>
                  ) : null}
                </div>
              ) : null}

              <div className="mt-5 space-y-3">
                {currentOptions.map((option) => (
                  <button
                    key={option.key}
                    type="button"
                    disabled={Boolean(feedback)}
                    onClick={() => {
                      setSelectedOption(option.key);
                      setSubmitError("");
                    }}
                    className={`w-full text-left transition-all duration-100 ease-linear hover:-translate-y-1 disabled:cursor-default disabled:hover:translate-y-0 ${getOptionCardClass(
                      option.key
                    )}`}
                  >
                    <div className="flex items-start gap-3">
                      <span className="neo-badge bg-white">{option.key}</span>
                      <div className="flex-1 space-y-2">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <p className="text-sm font-bold leading-relaxed">
                            {option.text}
                          </p>
                          {getOptionStatusLabel(option.key) ? (
                            <span className="neo-badge bg-white text-[10px]">
                              {getOptionStatusLabel(option.key)}
                            </span>
                          ) : null}
                        </div>
                        {feedback ? (
                          <p className="text-xs font-bold leading-relaxed">
                            {feedback.optionRationales[option.key] ?? ""}
                          </p>
                        ) : null}
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              {submitError ? (
                <div className="mt-4 rounded-[1.25rem] border-[3px] border-neo-ink bg-neo-accent p-4 shadow-neo-sm">
                  <p className="neo-label">提交失败</p>
                  <p className="mt-2 text-sm font-bold leading-relaxed">
                    {submitError}
                  </p>
                </div>
              ) : null}

              {feedback && feedbackHero ? (
                <div className="mt-5 space-y-4">
                  <div className={`rounded-[1.5rem] border-[3px] border-neo-ink ${feedbackHero.tone} p-5 shadow-neo`}>
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="neo-label">{feedbackHero.badge}</p>
                        <h3 className="mt-2 text-2xl font-black leading-tight">
                          {feedbackHero.title}
                        </h3>
                      </div>
                      <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full border-[3px] border-neo-ink bg-white shadow-neo-sm">
                        {feedbackHero.icon}
                      </span>
                    </div>
                    <p className="mt-3 text-sm font-bold leading-relaxed">
                      {feedbackHero.subtitle}
                    </p>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
                      <p className="neo-label">你的答案</p>
                      <p className="mt-2 text-lg font-black">
                        {feedback.submittedOption ?? selectedOption}. {selectedOptionText || "未找到选项文本"}
                      </p>
                    </div>
                    <div className="border-[3px] border-neo-ink bg-[#B8F7C1] p-4 shadow-neo-sm">
                      <p className="neo-label">正确答案</p>
                      <p className="mt-2 text-lg font-black">
                        {feedback.correctOption}. {correctOptionText || "未找到选项文本"}
                      </p>
                    </div>
                  </div>

                  {!feedback.isCorrect ? (
                    <div className="border-[3px] border-neo-ink bg-neo-accent p-4 shadow-neo-sm">
                      <div className="flex items-center gap-2">
                        <XCircle size={18} strokeWidth={2.8} />
                        <p className="neo-label">你选的这项为什么不对</p>
                      </div>
                      <p className="mt-2 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                        {selectedRationale || "这项的干扰点还需要结合完整解析一起看。"}
                      </p>
                    </div>
                  ) : (
                    <div className="border-[3px] border-neo-ink bg-[#B8F7C1] p-4 shadow-neo-sm">
                      <div className="flex items-center gap-2">
                        <CheckCircle2 size={18} strokeWidth={2.8} />
                        <p className="neo-label">这一步判断很稳</p>
                      </div>
                      <p className="mt-2 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                        {correctRationale || "你的选择和标准答案一致，可以继续用解析巩固理由。"}
                      </p>
                    </div>
                  )}

                  {!feedback.isCorrect ? (
                    <div className="border-[3px] border-neo-ink bg-[#B8F7C1] p-4 shadow-neo-sm">
                      <div className="flex items-center gap-2">
                        <BookOpenCheck size={18} strokeWidth={2.8} />
                        <p className="neo-label">正确选项为什么成立</p>
                      </div>
                      <p className="mt-2 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                        {correctRationale || "正确选项的理由见下面的标准解析。"}
                      </p>
                    </div>
                  ) : null}

                  <div className="border-[3px] border-neo-ink bg-white p-4 shadow-neo-sm">
                    <div className="flex items-center gap-2">
                      <Lightbulb size={18} strokeWidth={2.8} />
                      <p className="neo-label">标准解析</p>
                    </div>
                    <p className="mt-2 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                      {feedback.explanation}
                    </p>
                  </div>

                  {feedback.masteryEvaluation ? (
                    <div className="border-[3px] border-neo-ink bg-[#D9D2FF] p-4 shadow-neo-sm">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="neo-label">掌握度判断</p>
                          <h3 className="mt-2 text-xl font-black">
                            {masteryLevelLabel} · {Math.round(feedback.masteryEvaluation.mastery_score)} 分
                          </h3>
                        </div>
                        <span className="neo-badge bg-white">
                          评估 {Math.round(feedback.masteryEvaluation.score)}%
                        </span>
                      </div>
                      <p className="mt-3 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                        {feedback.personalizedFeedback || feedback.masteryEvaluation.feedback}
                      </p>
                      <div className="mt-4 grid gap-3 sm:grid-cols-3">
                        {[
                          ["准确性", feedback.masteryEvaluation.score_breakdown.accuracy],
                          ["完整度", feedback.masteryEvaluation.score_breakdown.completeness],
                          ["理解深度", feedback.masteryEvaluation.score_breakdown.understanding_depth],
                        ].map(([label, value]) => (
                          <div key={label} className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm">
                            <div className="flex items-center justify-between gap-2">
                              <p className="neo-label">{label}</p>
                              <p className="text-sm font-black">{Math.round(Number(value))}%</p>
                            </div>
                            <div className="mt-2 h-3 rounded-full border-[2px] border-neo-ink bg-neo-muted">
                              <div
                                className="h-full rounded-full bg-neo-secondary"
                                style={{ width: `${Math.max(0, Math.min(100, Number(value)))}%` }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span className="neo-badge bg-white">
                          RAG 参考 {feedback.masteryEvaluation.reference_doc_count} 条
                        </span>
                        {feedback.masteryEvaluation.score_breakdown.low_confidence ? (
                          <span className="neo-badge bg-neo-accent">
                            参考置信度偏低
                          </span>
                        ) : null}
                        {feedback.masteryEvaluation.weak_points.map((point) => (
                          <span key={point} className="neo-badge bg-white">
                            薄弱：{point}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  <div className="border-[3px] border-dashed border-neo-ink bg-neo-muted p-4">
                    <p className="neo-label">四个选项速记</p>
                    <div className="mt-3 space-y-2">
                      {currentOptions.map((option) => (
                        <div key={`rationale-${option.key}`} className="flex gap-2 text-xs font-bold leading-relaxed">
                          <span className="neo-badge bg-white text-[10px]">{option.key}</span>
                          <p className="flex-1">
                            {feedback.optionRationales[option.key] || "暂无单独说明。"}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}

              <div className="mt-5 flex flex-col gap-3">
                {!feedback ? (
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!selectedOption || isSubmitting}
                    className="neo-button w-full justify-center disabled:opacity-50"
                  >
                    {isSubmitting ? "正在判题..." : "提交作答"}
                  </button>
                ) : isLastQuestion ? (
                  <button
                    type="button"
                    onClick={() => {
                      markPracticeCompleted();
                      router.push("/chat");
                    }}
                    className="neo-button-secondary w-full justify-center"
                  >
                    练完了，回问答页继续
                    <ArrowRight size={16} strokeWidth={2.8} />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleNext}
                    className="neo-button-secondary w-full justify-center"
                  >
                    下一题
                    <ArrowRight size={16} strokeWidth={2.8} />
                  </button>
                )}
              </div>
            </section>
          </div>
        )}
      </main>

      <BottomNav />

      {isClearConfirmOpen && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-4 sm:items-center">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="clear-practice-pack-title"
            className="neo-card w-full max-w-md p-5"
          >
            <p className="neo-label">Practice Queue</p>
            <h2 id="clear-practice-pack-title" className="mt-2 text-xl font-black">
              清空当前练习题库？
            </h2>
            <p className="mt-3 text-sm font-bold leading-relaxed text-neo-ink/70">
              这个操作只会清空当前练习队列和页面进度。已经提交过的做题记录、掌握度和聊天历史都会保留。
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setIsClearConfirmOpen(false)}
                className="neo-button-ghost w-full justify-center"
              >
                取消
              </button>
              <button
                type="button"
                onClick={handleConfirmClearPracticePack}
                className="neo-button w-full justify-center bg-neo-accent"
              >
                确认清空
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
