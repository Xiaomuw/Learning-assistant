import { useMemo, useState } from "react";
import Taro, { useDidShow } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { ensureAuthSession, fetchLatestQuizBundle, fetchPracticeRecommendations, submitPracticeAttempt } from "@/services/api";
import { requireAuthUser } from "@/store/auth";
import {
  createSessionId,
  getStoredNotebookId,
  getStoredQuizState,
  setStoredQuizState,
  type StoredQuizState
} from "@/store/learning";
import type { PracticeAttemptResult, QuizItem } from "@/types/api";
import "./index.scss";

export default function PracticePage() {
  const [quizList, setQuizList] = useState<QuizItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedOption, setSelectedOption] = useState("");
  const [feedback, setFeedback] = useState<PracticeAttemptResult | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [notebookId, setNotebookId] = useState(getStoredNotebookId());
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const currentQuiz = quizList[currentIndex];
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
    await loadQuiz(user.id);
  }

  function quizKey(quiz: QuizItem | undefined, index = currentIndex) {
    return quiz?.question_id || `${index}:${quiz?.question || "quiz"}`;
  }

  function persistState(partial: Partial<StoredQuizState> = {}) {
    setStoredQuizState({
      sessionId,
      subjectId: notebookId,
      items: quizList,
      currentIndex,
      answers,
      ...partial
    });
  }

  async function loadQuiz(userId: string) {
    setLoading(true);
    setError("");
    const cached = getStoredQuizState();
    if (cached.items.length > 0) {
      const nextIndex = Math.min(cached.currentIndex || 0, cached.items.length - 1);
      setQuizList(cached.items);
      setCurrentIndex(nextIndex);
      setSessionId(cached.sessionId || "");
      setNotebookId(cached.subjectId || getStoredNotebookId());
      setAnswers(cached.answers || {});
      setSelectedOption((cached.answers || {})[quizKey(cached.items[nextIndex], nextIndex)] || "");
      setFeedback(null);
      setLoading(false);
      return;
    }

    try {
      const latest = await fetchLatestQuizBundle(userId);
      const latestItems = Array.isArray(latest.quiz_items) ? latest.quiz_items : [];
      if (latestItems.length > 0) {
        setQuizList(latestItems);
        setCurrentIndex(0);
        setSessionId(latest.session_id || "");
        setNotebookId(latest.subject_id || getStoredNotebookId());
        setAnswers({});
        setSelectedOption("");
        setFeedback(null);
        setStoredQuizState({
          sessionId: latest.session_id || "",
          subjectId: latest.subject_id || getStoredNotebookId(),
          items: latestItems,
          currentIndex: 0,
          answers: {}
        });
        return;
      }

      const recommendations = await fetchPracticeRecommendations(userId, getStoredNotebookId());
      const items = Array.isArray(recommendations.items) ? recommendations.items : [];
      setQuizList(items);
      setCurrentIndex(0);
      setNotebookId(recommendations.subject_id || getStoredNotebookId());
      setAnswers({});
      setSelectedOption("");
      setFeedback(null);
      if (items.length > 0) {
        setStoredQuizState({
          sessionId: "",
          subjectId: recommendations.subject_id || getStoredNotebookId(),
          items,
          currentIndex: 0,
          answers: {}
        });
      }
    } catch (err: any) {
      setError(err?.message || "暂时无法获取练习题");
    } finally {
      setLoading(false);
    }
  }

  function selectOption(key: string) {
    if (feedback || submitting) return;
    const nextAnswers = {
      ...answers,
      [quizKey(currentQuiz)]: key
    };
    setSelectedOption(key);
    setAnswers(nextAnswers);
    persistState({ answers: nextAnswers });
    setError("");
  }

  async function handleSubmit() {
    const user = requireAuthUser();
    if (!user || !currentQuiz || !selectedOption || feedback || submitting) return;

    const nextSessionId = currentQuiz.source_session_id || sessionId || getStoredQuizState().sessionId || createSessionId();
    const nextNotebookId = currentQuiz.subject_id || currentQuiz.notebook_id || notebookId || getStoredQuizState().subjectId || getStoredNotebookId();
    setSessionId(nextSessionId);
    setNotebookId(nextNotebookId);
    persistState({
      sessionId: nextSessionId,
      subjectId: nextNotebookId,
      answers: {
        ...answers,
        [quizKey(currentQuiz)]: selectedOption
      }
    });

    setSubmitting(true);
    setError("");
    try {
      const result = await submitPracticeAttempt({
        userId: user.id,
        sessionId: nextSessionId,
        notebookId: nextNotebookId,
        quizItem: currentQuiz,
        selectedOption
      });
      setFeedback(result);
    } catch (err: any) {
      setError(err?.message || "提交失败，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  function handleNext() {
    if (currentIndex >= quizList.length - 1) {
      Taro.switchTab({ url: "/pages/chat/index" });
      return;
    }
    const nextIndex = currentIndex + 1;
    setCurrentIndex(nextIndex);
    setSelectedOption(answers[quizKey(quizList[nextIndex], nextIndex)] || "");
    setFeedback(null);
    setError("");
    persistState({ currentIndex: nextIndex });
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
          <Text>正在加载练习题...</Text>
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
      ) : (
        <View className="card quiz-card">
          <View className="quiz-meta">
            <Text className="pill">{currentQuiz.difficulty || "练习"}</Text>
            <Text className="knowledge-point">{currentQuiz.knowledge_point || "综合"}</Text>
          </View>
          <Text className="question-text">{currentQuiz.question}</Text>

          <View className="option-list">
            {currentQuiz.options.map((option) => (
              <View
                key={option.key}
                className={`option-item ${optionClass(option.key)}`}
                onClick={() => selectOption(option.key)}
              >
                <Text className="option-key">{option.key}</Text>
                <Text className="option-text">{option.text}</Text>
              </View>
            ))}
          </View>

          {feedback ? (
            <View className={`feedback-card ${feedback.is_correct ? "ok" : "bad"}`}>
              <Text className="feedback-title">{feedback.is_correct ? "回答正确" : "再看看这一步"}</Text>
              <Text className="feedback-text">
                {feedback.personalized_feedback || feedback.explanation}
              </Text>
              <Text className="feedback-answer">正确答案：{feedback.correct_option}</Text>
            </View>
          ) : null}

          {error ? <Text className="error-text">{error}</Text> : null}

          {!feedback ? (
            <Button className="button-primary action-button" disabled={!selectedOption || submitting} loading={submitting} onClick={handleSubmit}>
              提交答案
            </Button>
          ) : (
            <Button className="button-primary action-button" onClick={handleNext}>
              {currentIndex >= quizList.length - 1 ? "回到问答" : "下一题"}
            </Button>
          )}
        </View>
      )}
    </View>
  );
}
