"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, HelpCircle, PencilRuler, Target } from "lucide-react";
import BottomNav from "@/components/BottomNav";
import {
  DEFAULT_USER_ID,
  fetchLatestQuiz,
  type QuizItem,
} from "@/lib/api";
import { loadStoredQuiz, persistQuiz } from "@/lib/learning-store";

export default function PracticePage() {
  const [quizList, setQuizList] = useState<QuizItem[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [userAnswer, setUserAnswer] = useState("");
  const [showResult, setShowResult] = useState(false);
  const [showHint, setShowHint] = useState(false);

  useEffect(() => {
    const cachedQuiz = loadStoredQuiz();
    setQuizList(cachedQuiz);

    if (cachedQuiz.length > 0) {
      return;
    }

    void fetchLatestQuiz(DEFAULT_USER_ID)
      .then((remoteQuiz) => {
        setQuizList(remoteQuiz);
        if (remoteQuiz.length > 0) {
          persistQuiz(remoteQuiz);
        }
      })
      .catch((error) => {
        console.error("加载最新题包失败:", error);
      });
  }, []);

  const currentQuiz = quizList[currentIndex] ?? null;
  const isLastQuestion = currentIndex >= quizList.length - 1;
  const knowledgePoints = Array.from(
    new Set(quizList.map((item) => item.knowledge_point))
  ).slice(0, 3);

  function handleSubmit() {
    if (!userAnswer.trim()) {
      return;
    }

    setShowResult(true);
  }

  function handleNext() {
    if (isLastQuestion) {
      return;
    }

    setCurrentIndex((previous) => previous + 1);
    setUserAnswer("");
    setShowResult(false);
    setShowHint(false);
  }

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-accent px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="neo-label">Practice Mode</p>
            <h1 className="mt-2 text-3xl font-black tracking-tight">刷题练习</h1>
            <p className="mt-3 text-sm font-bold leading-relaxed">
              把最近一次问答里生成的题包，拆成移动端更顺手的做题流程。
            </p>
          </div>

          <div className="neo-badge -rotate-3 bg-white">
            {quizList.length > 0 ? `${currentIndex + 1}/${quizList.length}` : "EMPTY"}
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        {quizList.length === 0 ? (
          <section className="neo-card-secondary animate-stamp-in p-5">
            <p className="neo-label">No Quiz Yet</p>
            <h2 className="mt-2 text-4xl font-black leading-none">
              题包还是空的
            </h2>
            <p className="mt-4 text-sm font-bold leading-relaxed">
              先回问答页让学习助手给你出题，题目会自动落到这里。
            </p>
            <Link href="/chat" className="neo-button mt-5 w-full justify-center">
              去问答页生成练习题
              <ArrowRight size={16} strokeWidth={2.8} />
            </Link>
          </section>
        ) : (
          <div className="space-y-4">
            <section className="neo-card-muted p-4">
              <div className="flex items-center gap-2">
                <PencilRuler size={16} strokeWidth={2.8} />
                <p className="neo-label">Practice Pack</p>
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

            <section className="neo-card animate-stamp-in bg-white p-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="neo-badge bg-neo-accent">
                  {currentQuiz?.difficulty ?? "基础"}
                </span>
                <span className="neo-badge bg-neo-secondary">
                  {currentQuiz?.knowledge_point ?? "综合"}
                </span>
              </div>

              <p className="mt-4 text-xl font-black leading-snug whitespace-pre-wrap">
                {currentQuiz?.question ?? ""}
              </p>

              {!showResult && (
                <div className="mt-4">
                  <button
                    type="button"
                    onClick={() => setShowHint((value) => !value)}
                    className="neo-button-ghost w-full justify-center"
                  >
                    <HelpCircle size={16} strokeWidth={2.8} />
                    {showHint ? "收起提示" : "查看提示"}
                  </button>

                  {showHint && (
                    <div className="neo-card-secondary mt-3 p-4">
                      <p className="neo-label">Hint</p>
                      <p className="mt-2 text-sm font-bold leading-relaxed">
                        {currentQuiz?.hint}
                      </p>
                    </div>
                  )}
                </div>
              )}

              <div className="mt-4 space-y-3">
                <label className="neo-label" htmlFor="practice-answer">
                  你的解法
                </label>
                <textarea
                  id="practice-answer"
                  value={userAnswer}
                  onChange={(event) => setUserAnswer(event.target.value)}
                  disabled={showResult}
                  placeholder="把你的思路、关键步骤、答案都写在这里。"
                  rows={5}
                  className="neo-input min-h-[150px] resize-none leading-relaxed disabled:bg-neo-bg"
                />
              </div>

              {showResult && (
                <div className="neo-card-secondary mt-4 p-4">
                  <p className="neo-label">参考答案</p>
                  <p className="mt-2 text-sm font-bold leading-relaxed whitespace-pre-wrap">
                    {currentQuiz?.answer}
                  </p>
                </div>
              )}

              <div className="mt-5 flex flex-col gap-3">
                {!showResult ? (
                  <button
                    type="button"
                    onClick={handleSubmit}
                    disabled={!userAnswer.trim()}
                    className="neo-button w-full justify-center"
                  >
                    提交作答
                  </button>
                ) : isLastQuestion ? (
                  <Link href="/chat" className="neo-button-secondary w-full justify-center">
                    练完了，回问答页继续
                    <ArrowRight size={16} strokeWidth={2.8} />
                  </Link>
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
    </div>
  );
}
