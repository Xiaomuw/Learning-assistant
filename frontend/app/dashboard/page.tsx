"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpenCheck,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  Lightbulb,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import BottomNav from "@/components/BottomNav";
import { useAuth } from "@/components/AuthProvider";
import {
  fetchLearningCenter,
  type LearningCenterChapter,
  type LearningCenterConcept,
  type LearningCenterNextMove,
  type LearningCenterResponse,
  type LearningCenterStatus,
  type LearningCenterSubject,
  type LearningCenterTopic,
} from "@/lib/api";

type ConceptWithPath = LearningCenterConcept & {
  subject_id: string;
  subject_name: string;
  chapter_id: string;
  chapter_name: string;
  topic_id: string;
  topic_name: string;
};

type SubjectSummary = {
  conceptCount: number;
  testedCount: number;
  weakCount: number;
  attemptCount: number;
  correctCount: number;
  wrongCount: number;
  masteryScore: number;
};

const DEFAULT_SUBJECT_ID = "data-structure";

const STATUS_LABELS: Record<LearningCenterStatus, string> = {
  unstarted: "未开始",
  weak: "薄弱",
  learning: "学习中",
  mastered: "已掌握",
};

const STATUS_TONES: Record<LearningCenterStatus, string> = {
  unstarted: "bg-white",
  weak: "bg-neo-accent",
  learning: "bg-neo-muted",
  mastered: "bg-neo-green",
};

function normalizePercent(value: number | null | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return 0;
  }
  const percent = value <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, Math.round(percent)));
}

function formatPercent(value: number | null | undefined) {
  return `${normalizePercent(value)}%`;
}

function formatDate(value: string | null | undefined) {
  if (!value) {
    return "暂无";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无";
  }
  return date.toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
}

function conceptCount(subject: LearningCenterSubject | null | undefined) {
  return (
    subject?.chapters.reduce(
      (chapterTotal, chapter) =>
        chapterTotal +
        chapter.topics.reduce(
          (topicTotal, topic) => topicTotal + topic.concepts.length,
          0
        ),
      0
    ) ?? 0
  );
}

function conceptPaths(subjects: LearningCenterSubject[]): ConceptWithPath[] {
  return subjects.flatMap((subject) =>
    subject.chapters.flatMap((chapter) =>
      chapter.topics.flatMap((topic) =>
        topic.concepts.map((concept) => ({
          ...concept,
          subject_id: subject.subject_id,
          subject_name: subject.subject_name,
          chapter_id: chapter.chapter_id,
          chapter_name: chapter.chapter_name,
          topic_id: topic.topic_id,
          topic_name: topic.topic_name,
        }))
      )
    )
  );
}

function chooseNextMove(
  subjects: LearningCenterSubject[],
  serverMove?: LearningCenterNextMove | null
): ConceptWithPath | null {
  const concepts = conceptPaths(subjects);
  if (concepts.length === 0) {
    return null;
  }

  const matchedServerMove = serverMove
    ? concepts.find((concept) => concept.concept_id === serverMove.concept_id)
    : null;
  if (matchedServerMove) {
    return matchedServerMove;
  }

  const sortByWeakness = (items: ConceptWithPath[]) =>
    [...items].sort((left, right) => {
      const leftScore = normalizePercent(left.p_mastery);
      const rightScore = normalizePercent(right.p_mastery);
      if (leftScore !== rightScore) {
        return leftScore - rightScore;
      }
      return right.wrong_count - left.wrong_count;
    });

  return (
    sortByWeakness(
      concepts.filter(
        (concept) => concept.status === "weak" && concept.attempt_count > 0
      )
    )[0] ??
    sortByWeakness(
      concepts.filter(
        (concept) => concept.status === "learning" && concept.attempt_count > 0
      )
    )[0] ??
    concepts.find(
      (concept) =>
        concept.status === "unstarted" &&
        concept.importance === "high" &&
        concept.exam_frequency === "high"
    ) ??
    concepts.find((concept) => concept.status === "unstarted") ??
    concepts[0]
  );
}

function buildChatHref(subjectId: string | undefined) {
  if (!subjectId) {
    return "/chat";
  }
  const params = new URLSearchParams({ subject: subjectId });
  return `/chat?${params.toString()}`;
}

function buildPracticeHref(concept: ConceptWithPath | null) {
  if (!concept) {
    return "/practice";
  }
  const params = new URLSearchParams({
    subject: concept.subject_id,
    concept: concept.concept_id,
    concept_name: concept.concept_name,
  });
  return `/practice?${params.toString()}`;
}

function chapterKey(subject: LearningCenterSubject, chapter: LearningCenterChapter) {
  return `${subject.subject_id}:${chapter.chapter_id}`;
}

function topicKey(chapter: LearningCenterChapter, topic: LearningCenterTopic) {
  return `${chapter.chapter_id}:${topic.topic_id}`;
}

function summaryForSubjects(subjects: LearningCenterSubject[]): SubjectSummary {
  const conceptTotal = subjects.reduce(
    (total, subject) => total + conceptCount(subject),
    0
  );
  const weightedMastery = subjects.reduce(
    (total, subject) => total + subject.mastery_score * conceptCount(subject),
    0
  );
  return {
    conceptCount: conceptTotal,
    testedCount: subjects.reduce(
      (total, subject) => total + (subject.tested_count ?? 0),
      0
    ),
    weakCount: subjects.reduce(
      (total, subject) => total + (subject.weak_count ?? 0),
      0
    ),
    attemptCount: subjects.reduce(
      (total, subject) => total + (subject.attempt_count ?? 0),
      0
    ),
    correctCount: subjects.reduce(
      (total, subject) => total + (subject.correct_count ?? 0),
      0
    ),
    wrongCount: subjects.reduce(
      (total, subject) => total + (subject.wrong_count ?? 0),
      0
    ),
    masteryScore:
      conceptTotal > 0 ? Math.round(weightedMastery / conceptTotal) : 0,
  };
}

function seedExpandedSubjects(
  subjects: LearningCenterSubject[],
  nextMove: ConceptWithPath | null
) {
  const preferredSubjectId =
    nextMove?.subject_id ??
    subjects.find((subject) => subject.subject_id === DEFAULT_SUBJECT_ID)
      ?.subject_id ??
    subjects[0]?.subject_id;
  return preferredSubjectId ? new Set([preferredSubjectId]) : new Set<string>();
}

function seedExpandedChapters(
  subjects: LearningCenterSubject[],
  nextMove: ConceptWithPath | null
) {
  if (!nextMove) {
    return new Set<string>();
  }
  const subject = subjects.find((item) => item.subject_id === nextMove.subject_id);
  const chapter = subject?.chapters.find(
    (item) => item.chapter_id === nextMove.chapter_id
  );
  return subject && chapter ? new Set([chapterKey(subject, chapter)]) : new Set<string>();
}

function seedExpandedTopics(
  subjects: LearningCenterSubject[],
  nextMove: ConceptWithPath | null
) {
  if (!nextMove) {
    return new Set<string>();
  }
  for (const subject of subjects) {
    for (const chapter of subject.chapters) {
      const topic = chapter.topics.find((item) => item.topic_id === nextMove.topic_id);
      if (topic) {
        return new Set([topicKey(chapter, topic)]);
      }
    }
  }
  return new Set<string>();
}

function ProgressBar({
  value,
  tone = "bg-neo-secondary",
}: {
  value: number;
  tone?: string;
}) {
  const percent = normalizePercent(value);
  return (
    <div className="h-4 border-[3px] border-neo-ink bg-white">
      <div
        className={`h-full border-r-[3px] border-neo-ink ${tone}`}
        style={{ width: `${Math.max(4, percent)}%` }}
      />
    </div>
  );
}

function StatBox({
  label,
  value,
  tone = "bg-white",
}: {
  label: string;
  value: string | number;
  tone?: string;
}) {
  return (
    <div className={`border-[3px] border-neo-ink p-3 shadow-neo-sm ${tone}`}>
      <p className="neo-label">{label}</p>
      <p className="mt-2 break-words text-2xl font-black">{value}</p>
    </div>
  );
}

function MiniStats({
  masteryScore,
  testedRatio,
  weakCount,
  attemptCount,
  correctCount,
  wrongCount,
}: {
  masteryScore: number;
  testedRatio: number;
  weakCount: number;
  attemptCount: number;
  correctCount: number;
  wrongCount: number;
}) {
  return (
    <div className="mt-3 flex flex-wrap gap-2 text-[11px] font-black">
      <span className="neo-badge bg-white">掌握 {formatPercent(masteryScore)}</span>
      <span className="neo-badge bg-white">已测 {formatPercent(testedRatio)}</span>
      <span className="neo-badge bg-neo-accent">薄弱 {weakCount}</span>
      <span className="neo-badge bg-white">练 {attemptCount}</span>
      <span className="neo-badge bg-neo-green">对 {correctCount}</span>
      <span className="neo-badge bg-neo-muted">错 {wrongCount}</span>
    </div>
  );
}

export default function DashboardPage() {
  const { user, isLoading } = useAuth();
  const userId = user?.id ?? "";
  const [learningCenter, setLearningCenter] =
    useState<LearningCenterResponse | null>(null);
  const [expandedSubjectIds, setExpandedSubjectIds] = useState<Set<string>>(new Set());
  const [expandedChapterIds, setExpandedChapterIds] = useState<Set<string>>(new Set());
  const [expandedTopicIds, setExpandedTopicIds] = useState<Set<string>>(new Set());
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [isLearningCenterLoading, setIsLearningCenterLoading] = useState(false);

  useEffect(() => {
    if (isLoading || !userId) {
      return;
    }

    let isMounted = true;
    setLoadError("");
    setIsLearningCenterLoading(true);

    void fetchLearningCenter(userId)
      .then((payload) => {
        if (!isMounted) {
          return;
        }
        const subjects = Array.isArray(payload.subjects) ? payload.subjects : [];
        const nextMove = chooseNextMove(subjects, payload.next_move);
        setLearningCenter({ ...payload, subjects });
        setExpandedSubjectIds(seedExpandedSubjects(subjects, nextMove));
        setExpandedChapterIds(seedExpandedChapters(subjects, nextMove));
        setExpandedTopicIds(seedExpandedTopics(subjects, nextMove));
      })
      .catch((error) => {
        if (!isMounted) {
          return;
        }
        console.error("加载学习中心失败:", error);
        setLoadError(
          error instanceof Error && error.message
            ? error.message
            : "学习中心暂时加载失败，请稍后重试。"
        );
      })
      .finally(() => {
        if (isMounted) {
          setIsLearningCenterLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [isLoading, reloadKey, userId]);

  const subjects = useMemo(
    () => learningCenter?.subjects ?? [],
    [learningCenter?.subjects]
  );
  const allSummary = useMemo(() => summaryForSubjects(subjects), [subjects]);
  const nextMove = useMemo(
    () => chooseNextMove(subjects, learningCenter?.next_move),
    [learningCenter?.next_move, subjects]
  );

  function toggleSubject(subjectId: string) {
    setExpandedSubjectIds((previous) => {
      const next = new Set(previous);
      if (next.has(subjectId)) {
        next.delete(subjectId);
      } else {
        next.add(subjectId);
      }
      return next;
    });
  }

  function toggleChapter(subject: LearningCenterSubject, chapter: LearningCenterChapter) {
    const key = chapterKey(subject, chapter);
    setExpandedChapterIds((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleTopic(chapter: LearningCenterChapter, topic: LearningCenterTopic) {
    const key = topicKey(chapter, topic);
    setExpandedTopicIds((previous) => {
      const next = new Set(previous);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-4">
        <div className="neo-card-secondary w-full p-5 text-center">
          <p className="neo-label">Dashboard</p>
          <p className="mt-3 text-lg font-black">正在恢复你的学习中心...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <header className="border-b-[3px] border-neo-ink bg-neo-muted px-4 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <p className="neo-label">Dashboard</p>
            <h1 className="mt-2 break-words text-3xl font-black">学习中心</h1>
            <p className="mt-3 max-w-[32rem] break-words text-sm font-bold leading-relaxed">
              这里不是“好不好看”的报表，而是你最近到底卡在哪、强在哪。
            </p>
          </div>

          <span className="neo-badge shrink-0 rotate-3 bg-white">REPORT</span>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-4 pb-24">
        <div className="space-y-4">
          {loadError ? (
            <section className="neo-card-accent p-4">
              <div className="flex items-start gap-3">
                <AlertTriangle className="shrink-0" size={18} strokeWidth={2.8} />
                <div className="min-w-0 flex-1">
                  <p className="neo-label">Learning Center</p>
                  <p className="mt-2 break-words text-sm font-black leading-relaxed">
                    {loadError}
                  </p>
                  <p className="mt-2 text-xs font-bold leading-relaxed">
                    408 架构接口恢复后会直接显示四科树，当前不再用空报表占位。
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setReloadKey((value) => value + 1)}
                className="neo-button mt-4 w-full justify-center text-xs"
              >
                <RefreshCw size={15} strokeWidth={2.8} />
                重新加载
              </button>
            </section>
          ) : null}

          {isLearningCenterLoading ? (
            <section className="neo-card-secondary p-5">
              <p className="neo-label">Loading</p>
              <p className="mt-3 text-lg font-black">正在按 408 架构整理掌握度...</p>
            </section>
          ) : null}

          {!isLearningCenterLoading && !loadError && subjects.length === 0 ? (
            <section className="neo-card-secondary p-5">
              <p className="neo-label">Empty</p>
              <h2 className="mt-2 text-2xl font-black">还没有可展示的 408 架构</h2>
              <p className="mt-3 text-sm font-bold leading-relaxed">
                学习中心需要后端返回 taxonomy；同步完成后会按学科、章节、主题、知识点展示。
              </p>
            </section>
          ) : null}

          {subjects.length > 0 ? (
            <>
              <section className="neo-card overflow-hidden bg-white">
                <div className="border-b-[3px] border-neo-ink bg-neo-secondary px-4 py-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <p className="neo-label">408 Report</p>
                      <h2 className="mt-1 break-words text-2xl font-black">
                        四科架构总览
                      </h2>
                    </div>
                    <span className="neo-badge shrink-0 bg-white">
                      {formatPercent(allSummary.masteryScore)}
                    </span>
                  </div>
                </div>

                <div className="space-y-4 p-4">
                  <div className="grid grid-cols-2 gap-3">
                    <StatBox
                      label="知识点"
                      value={allSummary.conceptCount}
                      tone="bg-neo-bg"
                    />
                    <StatBox
                      label="已测"
                      value={`${allSummary.testedCount}/${allSummary.conceptCount}`}
                      tone="bg-neo-muted"
                    />
                    <StatBox
                      label="薄弱点"
                      value={allSummary.weakCount}
                      tone="bg-neo-accent"
                    />
                    <StatBox
                      label="练习"
                      value={allSummary.attemptCount}
                      tone="bg-white"
                    />
                  </div>

                  <ProgressBar
                    value={allSummary.masteryScore}
                    tone="bg-neo-secondary"
                  />

                  <div className="grid grid-cols-2 gap-3">
                    <div className="border-[3px] border-neo-ink bg-neo-green p-3 shadow-neo-sm">
                      <p className="neo-label">正确</p>
                      <p className="mt-2 text-2xl font-black">{allSummary.correctCount}</p>
                    </div>
                    <div className="border-[3px] border-neo-ink bg-neo-accent p-3 shadow-neo-sm">
                      <p className="neo-label">错误</p>
                      <p className="mt-2 text-2xl font-black">{allSummary.wrongCount}</p>
                    </div>
                  </div>
                </div>
              </section>

              <section className="neo-card-secondary p-4">
                <div className="flex items-center gap-2">
                  <Lightbulb size={16} strokeWidth={2.8} />
                  <p className="neo-label">Next Move</p>
                </div>
                <p className="mt-3 break-words text-sm font-bold leading-relaxed">
                  {nextMove
                    ? `下一步最值得做的是：回到「${nextMove.concept_name}」。先让助手把概念讲清楚，再马上刷一组题。`
                    : "先选择一个 408 学科，系统会根据掌握度给出下一步。"}
                </p>
                {nextMove ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <span className="neo-badge bg-white">
                      {nextMove.subject_name}
                    </span>
                    <span className="neo-badge bg-white">{nextMove.topic_name}</span>
                    <span className={`neo-badge ${STATUS_TONES[nextMove.status]}`}>
                      {STATUS_LABELS[nextMove.status]}
                    </span>
                  </div>
                ) : null}
                <div className="mt-4 grid grid-cols-1 gap-3">
                  <Link
                    href={buildChatHref(nextMove?.subject_id)}
                    className="neo-button w-full justify-center"
                  >
                    <BrainCircuit size={16} strokeWidth={2.8} />
                    去问答页继续学
                  </Link>

                  <Link
                    href={buildPracticeHref(nextMove)}
                    className="neo-button-ghost w-full justify-center"
                  >
                    <Sparkles size={16} strokeWidth={2.8} />
                    去刷题页做题
                    <ArrowRight size={16} strokeWidth={2.8} />
                  </Link>
                </div>
              </section>

              <section className="space-y-3">
                <div className="flex items-center gap-2 px-1">
                  <BarChart3 size={16} strokeWidth={2.8} />
                  <p className="neo-label">408 知识架构</p>
                </div>

                {subjects.map((subject) => {
                  const isSubjectExpanded = expandedSubjectIds.has(subject.subject_id);
                  const subjectConceptCount = conceptCount(subject);
                  return (
                    <article
                      key={subject.subject_id}
                      className="overflow-hidden rounded-[1.5rem] border-[3px] border-neo-ink bg-white shadow-neo"
                    >
                      <button
                        type="button"
                        onClick={() => toggleSubject(subject.subject_id)}
                        aria-expanded={isSubjectExpanded}
                        className="flex w-full items-start justify-between gap-4 border-b-[3px] border-neo-ink bg-neo-muted px-4 py-4 text-left"
                      >
                        <div className="min-w-0">
                          <p className="neo-label">Subject</p>
                          <div className="mt-1 flex min-w-0 items-center gap-2">
                            {isSubjectExpanded ? (
                              <ChevronDown className="shrink-0" size={17} strokeWidth={2.8} />
                            ) : (
                              <ChevronRight className="shrink-0" size={17} strokeWidth={2.8} />
                            )}
                            <h3 className="break-words text-xl font-black">
                              {subject.subject_name}
                            </h3>
                          </div>
                          <MiniStats
                            masteryScore={subject.mastery_score}
                            testedRatio={subject.tested_ratio}
                            weakCount={subject.weak_count}
                            attemptCount={subject.attempt_count}
                            correctCount={subject.correct_count}
                            wrongCount={subject.wrong_count}
                          />
                        </div>
                        <div className="shrink-0 text-right">
                          <span className="neo-badge bg-white">
                            {formatPercent(subject.mastery_score)}
                          </span>
                          <p className="mt-2 text-[11px] font-black">
                            已测 {subject.tested_count}/{subjectConceptCount}
                          </p>
                        </div>
                      </button>

                      {isSubjectExpanded ? (
                        <div className="space-y-3 bg-neo-bg p-3">
                          {subject.chapters.map((chapter) => {
                            const isChapterExpanded = expandedChapterIds.has(
                              chapterKey(subject, chapter)
                            );
                            return (
                              <section
                                key={chapter.chapter_id}
                                className="overflow-hidden border-[3px] border-neo-ink bg-white shadow-neo-sm"
                              >
                                <button
                                  type="button"
                                  onClick={() => toggleChapter(subject, chapter)}
                                  aria-expanded={isChapterExpanded}
                                  className="flex w-full items-start justify-between gap-3 bg-white px-4 py-4 text-left"
                                >
                                  <div className="min-w-0">
                                    <div className="flex items-center gap-2">
                                      {isChapterExpanded ? (
                                        <ChevronDown
                                          className="shrink-0"
                                          size={16}
                                          strokeWidth={2.8}
                                        />
                                      ) : (
                                        <ChevronRight
                                          className="shrink-0"
                                          size={16}
                                          strokeWidth={2.8}
                                        />
                                      )}
                                      <h4 className="break-words text-base font-black">
                                        {chapter.chapter_name}
                                      </h4>
                                    </div>
                                    <MiniStats
                                      masteryScore={chapter.mastery_score}
                                      testedRatio={chapter.tested_ratio}
                                      weakCount={chapter.weak_count}
                                      attemptCount={chapter.attempt_count}
                                      correctCount={chapter.correct_count}
                                      wrongCount={chapter.wrong_count}
                                    />
                                  </div>
                                  <span className="neo-badge shrink-0 bg-white">
                                    {formatPercent(chapter.mastery_score)}
                                  </span>
                                </button>

                                {isChapterExpanded ? (
                                  <div className="divide-y-[3px] divide-neo-ink border-t-[3px] border-neo-ink">
                                    {chapter.topics.map((topic) => {
                                      const isTopicExpanded = expandedTopicIds.has(
                                        topicKey(chapter, topic)
                                      );
                                      return (
                                        <div key={topic.topic_id} className="bg-neo-bg">
                                          <button
                                            type="button"
                                            onClick={() => toggleTopic(chapter, topic)}
                                            aria-expanded={isTopicExpanded}
                                            className="flex w-full items-start justify-between gap-3 bg-white px-4 py-4 text-left"
                                          >
                                            <div className="min-w-0">
                                              <div className="flex items-center gap-2">
                                                {isTopicExpanded ? (
                                                  <ChevronDown
                                                    className="shrink-0"
                                                    size={16}
                                                    strokeWidth={2.8}
                                                  />
                                                ) : (
                                                  <ChevronRight
                                                    className="shrink-0"
                                                    size={16}
                                                    strokeWidth={2.8}
                                                  />
                                                )}
                                                <p className="break-words text-sm font-black">
                                                  {topic.topic_name}
                                                </p>
                                              </div>
                                              <MiniStats
                                                masteryScore={topic.mastery_score}
                                                testedRatio={topic.tested_ratio}
                                                weakCount={topic.weak_count}
                                                attemptCount={topic.attempt_count}
                                                correctCount={topic.correct_count}
                                                wrongCount={topic.wrong_count}
                                              />
                                            </div>
                                            <span className="neo-badge shrink-0 bg-white">
                                              {topic.tested_count}/{topic.concepts.length}
                                            </span>
                                          </button>

                                          {isTopicExpanded ? (
                                            <div className="grid gap-3 px-4 pb-4 sm:grid-cols-2">
                                              {topic.concepts.map((concept) => {
                                                const statusTone =
                                                  STATUS_TONES[concept.status] ?? "bg-white";
                                                const conceptForHref: ConceptWithPath = {
                                                  ...concept,
                                                  subject_id: subject.subject_id,
                                                  subject_name: subject.subject_name,
                                                  chapter_id: chapter.chapter_id,
                                                  chapter_name: chapter.chapter_name,
                                                  topic_id: topic.topic_id,
                                                  topic_name: topic.topic_name,
                                                };
                                                return (
                                                  <article
                                                    key={concept.concept_id}
                                                    className="border-[3px] border-neo-ink bg-white p-3 shadow-neo-sm"
                                                  >
                                                    <div className="flex items-start justify-between gap-2">
                                                      <div className="min-w-0">
                                                        <p className="break-words text-sm font-black leading-relaxed">
                                                          {concept.concept_name}
                                                        </p>
                                                        <p className="mt-1 break-words text-[11px] font-bold text-neo-ink/65">
                                                          {concept.concept_id}
                                                        </p>
                                                      </div>
                                                      <span className={`neo-badge shrink-0 ${statusTone}`}>
                                                        {STATUS_LABELS[concept.status]}
                                                      </span>
                                                    </div>

                                                    <div className="mt-3 flex flex-wrap gap-2">
                                                      <span
                                                        className={`neo-badge text-[10px] ${
                                                          concept.tested ? "bg-neo-green" : "bg-white"
                                                        }`}
                                                      >
                                                        {concept.tested
                                                          ? `已测 ${concept.attempt_count} 次`
                                                          : "未测"}
                                                      </span>
                                                      <span className="neo-badge bg-white text-[10px]">
                                                        题库 {concept.question_count}
                                                      </span>
                                                    </div>

                                                    <div className="mt-3">
                                                      <ProgressBar
                                                        value={concept.p_mastery}
                                                        tone={statusTone}
                                                      />
                                                    </div>

                                                    <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                                                      <div className="border-[2px] border-neo-ink bg-neo-bg px-2 py-2">
                                                        <p className="neo-label">练</p>
                                                        <p className="text-sm font-black">
                                                          {concept.attempt_count}
                                                        </p>
                                                      </div>
                                                      <div className="border-[2px] border-neo-ink bg-neo-green px-2 py-2">
                                                        <p className="neo-label">对</p>
                                                        <p className="text-sm font-black">
                                                          {concept.correct_count}
                                                        </p>
                                                      </div>
                                                      <div className="border-[2px] border-neo-ink bg-neo-accent px-2 py-2">
                                                        <p className="neo-label">错</p>
                                                        <p className="text-sm font-black">
                                                          {concept.wrong_count}
                                                        </p>
                                                      </div>
                                                    </div>

                                                    <div className="mt-3 flex flex-wrap gap-2">
                                                      <span className="neo-badge bg-white text-[10px]">
                                                        重要 {concept.importance}
                                                      </span>
                                                      <span className="neo-badge bg-white text-[10px]">
                                                        频率 {concept.exam_frequency}
                                                      </span>
                                                      <span className="neo-badge bg-white text-[10px]">
                                                        {formatDate(concept.last_practiced_at)}
                                                      </span>
                                                    </div>

                                                    <Link
                                                      href={buildPracticeHref(conceptForHref)}
                                                      className="neo-button-ghost mt-3 w-full justify-center text-[11px]"
                                                    >
                                                      <BookOpenCheck size={14} strokeWidth={2.8} />
                                                      针对它刷题
                                                    </Link>
                                                  </article>
                                                );
                                              })}
                                            </div>
                                          ) : null}
                                        </div>
                                      );
                                    })}
                                  </div>
                                ) : null}
                              </section>
                            );
                          })}
                        </div>
                      ) : null}
                    </article>
                  );
                })}
              </section>
            </>
          ) : null}
        </div>
      </main>

      <BottomNav />
    </div>
  );
}
