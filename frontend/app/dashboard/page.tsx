"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import BottomNav from "@/components/BottomNav";
import { useAuth } from "@/components/AuthProvider";
import {
  fetchKnowledgeMastery,
  fetchLearningCenter,
  fetchUserMemory,
  type KnowledgeMastery,
  type LearningCenterConcept,
  type LearningCenterResponse,
  type LearningCenterSubject,
  type Memory,
} from "@/lib/api";
import { loadStoredNotebookId, setLearningStoreUser } from "@/lib/learning-store";

const EMPTY_MEMORY: Memory = { weak_points: [], error_count: {}, recent_topics: [], last_session: "" };
const STATUS_LABELS: Record<string, string> = { unstarted: "未开始", weak: "薄弱", learning: "学习中", mastered: "已掌握" };
const STATUS_TONES: Record<string, string> = { unstarted: "bg-white", weak: "bg-neo-accent", learning: "bg-neo-muted", mastered: "bg-neo-green" };

interface ConceptWithPath {
  concept_id: string;
  concept_name: string;
  p_mastery: number;
  status: string;
  test_status: string;
  attempt_count: number;
  question_count: number;
  subjectId: string;
  subjectName: string;
  chapterName: string;
  topicName: string;
}

function percent(v: number | undefined) {
  const s = Number(v || 0);
  return `${Math.round(s <= 1 ? s * 100 : s)}%`;
}

function flattenConcepts(subjects: LearningCenterSubject[]): ConceptWithPath[] {
  const out: ConceptWithPath[] = [];
  subjects.forEach((s) =>
    s.chapters.forEach((c) =>
      c.topics.forEach((t) =>
        t.concepts.forEach((concept) => {
          out.push({
            concept_id: concept.concept_id,
            concept_name: concept.concept_name,
            p_mastery: concept.p_mastery,
            status: concept.status,
            test_status: concept.test_status,
            attempt_count: concept.attempt_count,
            question_count: concept.question_count,
            subjectId: s.subject_id,
            subjectName: s.subject_name,
            chapterName: c.chapter_name,
            topicName: t.topic_name,
          });
        })
      )
    )
  );
  return out;
}

function preferredConcepts(concepts: ConceptWithPath[]) {
  return concepts
    .filter((c) => c.status !== "mastered" || c.test_status === "untested")
    .sort((a, b) => {
      const ap = a.status === "weak" ? 0 : a.test_status === "untested" ? 1 : 2;
      const bp = b.status === "weak" ? 0 : b.test_status === "untested" ? 1 : 2;
      return ap - bp || (b.question_count || 0) - (a.question_count || 0);
    })
    .slice(0, 8);
}

export default function DashboardPage() {
  const router = useRouter();
  const { user, isLoading } = useAuth();
  const userId = user?.id ?? "";
  const [memory, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [masteryItems, setMasteryItems] = useState<KnowledgeMastery[]>([]);
  const [learningCenter, setLearningCenter] = useState<LearningCenterResponse | null>(null);
  const [expandedSubjects, setExpandedSubjects] = useState<Record<string, boolean>>({});
  const [expandedChapters, setExpandedChapters] = useState<Record<string, boolean>>({});
  const [expandedTopics, setExpandedTopics] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const concepts = useMemo(() => flattenConcepts(learningCenter?.subjects || []), [learningCenter]);
  const suggested = useMemo(() => preferredConcepts(concepts), [concepts]);
  const nextConcept = useMemo(() => {
    const nm = learningCenter?.next_move;
    if (!nm?.concept_id) return null;
    return concepts.find((c) => c.concept_id === nm.concept_id) || null;
  }, [concepts, learningCenter?.next_move]);
  const weakCount = concepts.filter((c) => c.status === "weak").length;
  const untestedCount = concepts.filter((c) => c.test_status === "untested").length;

  useEffect(() => {
    if (isLoading || !userId) return;
    setLearningStoreUser(userId);
    void loadDashboard();
  }, [isLoading, userId]);

  async function loadDashboard() {
    setLoading(true);
    setError("");
    try {
      const [memResult, masteryResult, lcResult] = await Promise.allSettled([
        fetchUserMemory(userId),
        fetchKnowledgeMastery(userId, loadStoredNotebookId()),
        fetchLearningCenter(userId),
      ]);
      if (memResult.status === "fulfilled") setMemory(memResult.value || EMPTY_MEMORY);
      if (masteryResult.status === "fulfilled") {
        const payload = masteryResult.value as { items?: KnowledgeMastery[] };
        setMasteryItems(Array.isArray(payload?.items) ? payload.items : []);
      }
      if (lcResult.status === "fulfilled") setLearningCenter(lcResult.value || null);
      if (lcResult.status === "rejected") setError((lcResult.reason as Error)?.message || "学习中心加载失败");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }

  function startPractice(c: ConceptWithPath) {
    const params = new URLSearchParams({ subject: c.subjectId, concept: c.concept_id, concept_name: c.concept_name });
    router.push(`/practice?${params.toString()}`);
  }

  function toggle(setter: React.Dispatch<React.SetStateAction<Record<string, boolean>>>, key: string) {
    setter((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  if (isLoading || !user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg">
        <div className="neo-card-secondary p-5 text-center">
          <p className="text-lg font-black">正在加载...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-neo-bg">
      <main className="flex-1 space-y-4 overflow-y-auto px-4 py-4 pb-24">
        <h1 className="text-3xl font-black">学习中心</h1>
        <p className="text-sm font-bold text-neo-ink/60">知识图谱进度和下一步建议。</p>

        {loading ? <div className="neo-card-secondary p-4"><p className="font-bold">正在加载...</p></div> : null}
        {error ? (
          <div className="neo-card-accent p-4">
            <p className="text-sm font-bold">{error}</p>
            <button type="button" className="neo-button mt-3 w-full justify-center text-xs" onClick={loadDashboard}>重试</button>
          </div>
        ) : null}

        {/* 统计 */}
        <div className="grid grid-cols-3 gap-3">
          <div className="neo-card flex flex-col items-center p-3"><span className="text-2xl font-black">{concepts.length || masteryItems.length}</span><span className="neo-label">知识点</span></div>
          <div className="neo-card-accent flex flex-col items-center p-3"><span className="text-2xl font-black">{weakCount || memory.weak_points?.length || 0}</span><span className="neo-label">薄弱点</span></div>
          <div className="neo-card flex flex-col items-center p-3"><span className="text-2xl font-black">{untestedCount}</span><span className="neo-label">待检测</span></div>
        </div>

        {/* 下一步建议 */}
        {(learningCenter?.next_move || suggested[0]) ? (
          <div className="neo-card-secondary p-4">
            <p className="neo-label">下一步建议</p>
            <h2 className="mt-2 text-xl font-black">{nextConcept?.concept_name || learningCenter?.next_move?.concept_name || suggested[0]?.concept_name}</h2>
            <p className="mt-2 text-sm font-bold text-neo-ink/70">{learningCenter?.next_move?.reason || "优先练还没测过或掌握度较弱的知识点。"}</p>
            <button type="button" className="neo-button mt-3 w-full justify-center" onClick={() => { const c = nextConcept || suggested[0]; if (c) startPractice(c); }}>开始定向练习</button>
          </div>
        ) : null}

        {/* 推荐练习点 */}
        <div className="neo-card p-4">
          <p className="neo-label">推荐练习点</p>
          {suggested.map((c) => (
            <button key={c.concept_id} type="button" className="mt-3 flex w-full items-center justify-between border-[3px] border-neo-ink bg-neo-bg p-3 text-left shadow-neo-sm first:mt-2" onClick={() => startPractice(c)}>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-black">{c.concept_name}</p>
                <p className="mt-1 text-[11px] font-bold text-neo-ink/60">{c.subjectName} / {c.chapterName} / {c.topicName}</p>
                <p className="mt-1 text-[11px] font-bold text-neo-ink/50">掌握 {percent(c.p_mastery)} · 练习 {c.attempt_count} 次</p>
              </div>
              <span className={`neo-badge shrink-0 ${STATUS_TONES[c.status] || "bg-white"}`}>{c.test_status === "untested" ? "待测" : STATUS_LABELS[c.status] || c.status}</span>
            </button>
          ))}
          {!suggested.length ? <p className="mt-2 text-sm font-bold text-neo-ink/50">暂无可推荐的练习点。</p> : null}
        </div>

        {/* 知识架构 */}
        <div className="neo-card p-4">
          <p className="neo-label">知识架构</p>
          {(learningCenter?.subjects || []).map((subject) => {
            const sOpen = Boolean(expandedSubjects[subject.subject_id]);
            return (
              <div key={subject.subject_id} className="mt-3 border-[3px] border-neo-ink bg-white shadow-neo-sm first:mt-2">
                <button type="button" className="flex w-full items-center justify-between bg-neo-muted p-3 text-left" onClick={() => toggle(setExpandedSubjects, subject.subject_id)}>
                  <div className="min-w-0">
                    <p className="text-base font-black">{subject.subject_name}</p>
                    <p className="mt-1 text-[11px] font-bold text-neo-ink/60">掌握 {percent(subject.mastery_score)} · 已测 {subject.tested_count} · 待测 {subject.untested_count}</p>
                  </div>
                  <span className="text-xs font-black text-neo-ink/60">{sOpen ? "收起" : "展开"}</span>
                </button>
                {sOpen ? (
                  <div className="space-y-2 border-t-[3px] border-neo-ink bg-neo-bg p-2">
                    {subject.chapters.map((chapter) => {
                      const cKey = `${subject.subject_id}:${chapter.chapter_id}`;
                      const cOpen = Boolean(expandedChapters[cKey]);
                      return (
                        <div key={cKey} className="border-[3px] border-neo-ink bg-white">
                          <button type="button" className="flex w-full items-center justify-between p-3 text-left" onClick={() => toggle(setExpandedChapters, cKey)}>
                            <div className="min-w-0">
                              <p className="text-sm font-black">{chapter.chapter_name}</p>
                              <p className="mt-1 text-[11px] font-bold text-neo-ink/60">掌握 {percent(chapter.mastery_score)} · 已测 {chapter.tested_count} · 薄弱 {chapter.weak_count}</p>
                            </div>
                            <span className="text-xs font-black text-neo-ink/60">{cOpen ? "收起" : "展开"}</span>
                          </button>
                          {cOpen ? (
                            <div className="space-y-2 border-t-[3px] border-neo-ink p-2">
                              {chapter.topics.map((topic) => {
                                const tKey = `${cKey}:${topic.topic_id}`;
                                const tOpen = Boolean(expandedTopics[tKey]);
                                return (
                                  <div key={tKey} className="border-[3px] border-neo-ink bg-neo-bg">
                                    <button type="button" className="flex w-full items-center justify-between p-2 text-left" onClick={() => toggle(setExpandedTopics, tKey)}>
                                      <div className="min-w-0">
                                        <p className="text-xs font-black">{topic.topic_name}</p>
                                        <p className="text-[10px] font-bold text-neo-ink/60">掌握 {percent(topic.mastery_score)} · 已测 {topic.tested_count}/{topic.concepts.length}</p>
                                      </div>
                                      <span className="text-[10px] font-black text-neo-ink/60">{tOpen ? "收起" : "展开"}</span>
                                    </button>
                                    {tOpen ? (
                                      <div className="space-y-1 border-t-[3px] border-neo-ink p-2">
                                        {topic.concepts.map((concept) => (
                                          <button key={concept.concept_id} type="button" className="flex w-full items-center justify-between border border-neo-ink/20 bg-white p-2 text-left" onClick={() => {
                                            const params = new URLSearchParams({ subject: subject.subject_id, concept: concept.concept_id, concept_name: concept.concept_name });
                                            router.push(`/practice?${params.toString()}`);
                                          }}>
                                            <div className="min-w-0">
                                              <p className="text-xs font-black">{concept.concept_name}</p>
                                              <p className="text-[10px] font-bold text-neo-ink/50">掌握 {percent(concept.p_mastery)} · {concept.attempt_count} 次</p>
                                            </div>
                                            <span className={`neo-badge text-[9px] ${STATUS_TONES[concept.status] || "bg-white"}`}>{concept.test_status === "untested" ? "待测" : STATUS_LABELS[concept.status] || concept.status}</span>
                                          </button>
                                        ))}
                                      </div>
                                    ) : null}
                                  </div>
                                );
                              })}
                            </div>
                          ) : null}
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            );
          })}
          {!(learningCenter?.subjects || []).length ? <p className="mt-2 text-sm font-bold text-neo-ink/50">暂无知识架构数据。</p> : null}
        </div>

        {/* 近期主题 */}
        <div className="neo-card p-4">
          <p className="neo-label">近期主题</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {(memory.recent_topics || []).slice(0, 6).map((t) => (<span key={t} className="neo-badge bg-white">{t}</span>))}
            {!(memory.recent_topics || []).length ? <p className="text-sm font-bold text-neo-ink/50">还没有近期主题。</p> : null}
          </div>
        </div>
      </main>
      <BottomNav />
    </div>
  );
}
