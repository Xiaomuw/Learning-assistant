import { useEffect, useMemo, useState } from "react";
import Taro, { useDidShow } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { ensureAuthSession, fetchKnowledgeMastery, fetchLearningCenter, fetchUserMemory } from "@/services/api";
import { requireAuthUser } from "@/store/auth";
import {
  getStoredNotebookId,
  setLearningCenterTarget,
  setLearningStoreUser,
  setStoredMemory,
  setStoredNotebookId
} from "@/store/learning";
import type {
  KnowledgeMastery,
  LearningCenterChapter,
  LearningCenterConcept,
  LearningCenterNextMove,
  LearningCenterResponse,
  LearningCenterSubject,
  LearningCenterTopic,
  Memory
} from "@/types/api";
import "./index.scss";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: ""
};

const STATUS_LABELS: Record<string, string> = {
  unstarted: "未开始",
  weak: "薄弱",
  learning: "学习中",
  mastered: "已掌握"
};

interface ConceptWithPath extends LearningCenterConcept {
  subjectName: string;
  chapterName: string;
  topicName: string;
}

function percent(value: number | undefined) {
  const score = Number(value || 0);
  return `${Math.round(score > 1 ? score : score * 100)}%`;
}

function flattenConcepts(subjects: LearningCenterSubject[]): ConceptWithPath[] {
  const concepts: ConceptWithPath[] = [];
  subjects.forEach((subject) => {
    subject.chapters.forEach((chapter) => {
      chapter.topics.forEach((topic) => {
        topic.concepts.forEach((concept) => {
          concepts.push({
            ...concept,
            subject_id: concept.subject_id || subject.subject_id,
            chapter_id: concept.chapter_id || chapter.chapter_id,
            topic_id: concept.topic_id || topic.topic_id,
            subjectName: subject.subject_name,
            chapterName: chapter.chapter_name,
            topicName: topic.topic_name
          });
        });
      });
    });
  });
  return concepts;
}

function preferredConcepts(concepts: ConceptWithPath[]) {
  return concepts
    .filter((concept) => concept.status !== "mastered" || concept.test_status === "untested")
    .sort((left, right) => {
      const leftPriority = left.status === "weak" ? 0 : left.test_status === "untested" ? 1 : 2;
      const rightPriority = right.status === "weak" ? 0 : right.test_status === "untested" ? 1 : 2;
      return leftPriority - rightPriority || (right.question_count || 0) - (left.question_count || 0);
    })
    .slice(0, 8);
}

function nextMoveConcept(concepts: ConceptWithPath[], nextMove?: LearningCenterNextMove | null) {
  if (!nextMove?.concept_id) return null;
  return concepts.find((concept) => concept.concept_id === nextMove.concept_id) || null;
}

function chapterKey(subjectId: string, chapterId: string) {
  return `${subjectId}:${chapterId || "chapter"}`;
}

function topicKey(subjectId: string, chapterId: string, topicId: string) {
  return `${subjectId}:${chapterId || "chapter"}:${topicId || "topic"}`;
}

function findExpansionPath(subjects: LearningCenterSubject[], nextMove?: LearningCenterNextMove | null) {
  if (!subjects.length) return null;

  for (const subject of subjects) {
    for (const chapter of subject.chapters) {
      for (const topic of chapter.topics) {
        const matchesConcept = Boolean(
          nextMove?.concept_id && topic.concepts.some((concept) => concept.concept_id === nextMove.concept_id)
        );
        const matchesPath = Boolean(
          nextMove?.subject_id === subject.subject_id &&
            (!nextMove.chapter_id || nextMove.chapter_id === chapter.chapter_id) &&
            (!nextMove.topic_id || nextMove.topic_id === topic.topic_id)
        );
        if (matchesConcept || matchesPath) {
          return {
            subjectId: subject.subject_id,
            chapterId: chapter.chapter_id,
            topicId: topic.topic_id
          };
        }
      }
    }
  }

  const fallbackSubject = nextMove?.subject_id
    ? subjects.find((subject) => subject.subject_id === nextMove.subject_id)
    : null;
  return {
    subjectId: fallbackSubject?.subject_id || subjects[0].subject_id,
    chapterId: "",
    topicId: ""
  };
}

export default function DashboardPage() {
  const [memory, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [mastery, setMastery] = useState<KnowledgeMastery[]>([]);
  const [learningCenter, setLearningCenter] = useState<LearningCenterResponse | null>(null);
  const [expandedSubjectIds, setExpandedSubjectIds] = useState<Record<string, boolean>>({});
  const [expandedChapterIds, setExpandedChapterIds] = useState<Record<string, boolean>>({});
  const [expandedTopicIds, setExpandedTopicIds] = useState<Record<string, boolean>>({});
  const [expandedConceptGroups, setExpandedConceptGroups] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const concepts = useMemo(
    () => flattenConcepts(learningCenter?.subjects || []),
    [learningCenter]
  );
  const suggestedConcepts = useMemo(() => preferredConcepts(concepts), [concepts]);
  const nextConcept = useMemo(
    () => nextMoveConcept(concepts, learningCenter?.next_move),
    [concepts, learningCenter?.next_move]
  );
  const weakConceptCount = concepts.filter((concept) => concept.status === "weak").length;
  const untestedConceptCount = concepts.filter((concept) => concept.test_status === "untested").length;

  useDidShow(() => {
    void bootstrapDashboard();
  });

  useEffect(() => {
    const subjects = learningCenter?.subjects || [];
    const expansion = findExpansionPath(subjects, learningCenter?.next_move);
    setExpandedSubjectIds(expansion?.subjectId ? { [expansion.subjectId]: true } : {});
    setExpandedChapterIds(
      expansion?.subjectId && expansion.chapterId
        ? { [chapterKey(expansion.subjectId, expansion.chapterId)]: true }
        : {}
    );
    setExpandedTopicIds(
      expansion?.subjectId && expansion.chapterId && expansion.topicId
        ? { [topicKey(expansion.subjectId, expansion.chapterId, expansion.topicId)]: true }
        : {}
    );
    setExpandedConceptGroups({});
  }, [learningCenter]);

  async function bootstrapDashboard() {
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    setLearningStoreUser(user.id);
    await loadDashboard(user.id);
  }

  async function loadDashboard(userId: string) {
    setLoading(true);
    setError("");
    const errors: string[] = [];
    try {
      const memoryPayload = await fetchUserMemory(userId);
      setMemory(memoryPayload || EMPTY_MEMORY);
      setStoredMemory(memoryPayload || EMPTY_MEMORY);
    } catch (err: any) {
      errors.push(err?.message || "学习记忆加载失败");
      setMemory(EMPTY_MEMORY);
    }

    try {
      const masteryPayload = await fetchKnowledgeMastery(userId, getStoredNotebookId());
      setMastery(Array.isArray(masteryPayload.items) ? masteryPayload.items : []);
    } catch (err: any) {
      errors.push(err?.message || "掌握度记录加载失败");
      setMastery([]);
    }

    try {
      const centerPayload = await fetchLearningCenter(userId);
      setLearningCenter(centerPayload || null);
    } catch (err: any) {
      errors.push(err?.message || "学习中心加载失败");
      setLearningCenter(null);
    }

    setError(errors[0] || "");
    setLoading(false);
  }

  function startConceptPractice(concept: ConceptWithPath, reason?: string) {
    setStoredNotebookId(concept.subject_id);
    setLearningCenterTarget({
      subjectId: concept.subject_id,
      subjectName: concept.subjectName,
      chapterId: concept.chapter_id || "",
      chapterName: concept.chapterName,
      topicId: concept.topic_id || "",
      topicName: concept.topicName,
      conceptId: concept.concept_id,
      conceptName: concept.concept_name,
      reason: reason || "学习中心定向练习"
    });
    Taro.switchTab({ url: "/pages/practice/index" });
  }

  function startTreeConceptPractice(
    subject: LearningCenterSubject,
    chapter: LearningCenterChapter,
    topic: LearningCenterTopic,
    concept: LearningCenterConcept
  ) {
    setStoredNotebookId(concept.subject_id || subject.subject_id);
    setLearningCenterTarget({
      subjectId: concept.subject_id || subject.subject_id,
      subjectName: subject.subject_name,
      chapterId: concept.chapter_id || chapter.chapter_id || "",
      chapterName: chapter.chapter_name,
      topicId: concept.topic_id || topic.topic_id || "",
      topicName: topic.topic_name,
      conceptId: concept.concept_id,
      conceptName: concept.concept_name,
      reason: "知识架构定向练习"
    });
    Taro.switchTab({ url: "/pages/practice/index" });
  }

  function toggleSubject(subjectId: string) {
    setExpandedSubjectIds((current) => ({ ...current, [subjectId]: !current[subjectId] }));
  }

  function toggleChapter(key: string) {
    setExpandedChapterIds((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleTopic(key: string) {
    setExpandedTopicIds((current) => ({ ...current, [key]: !current[key] }));
  }

  function toggleConceptGroup(key: string) {
    setExpandedConceptGroups((current) => ({ ...current, [key]: !current[key] }));
  }

  function startNextMove() {
    if (nextConcept) {
      startConceptPractice(nextConcept, learningCenter?.next_move?.reason || "下一步建议");
      return;
    }
    if (suggestedConcepts[0]) {
      startConceptPractice(suggestedConcepts[0], "推荐练习");
    }
  }

  return (
    <View className="page dashboard-page">
      <Text className="page-title">学习中心</Text>
      <Text className="page-subtitle">这里汇总最近学习轨迹、知识图谱进度和下一步练习建议。</Text>

      {loading ? (
        <View className="card summary-card">
          <Text>正在加载...</Text>
        </View>
      ) : null}

      {error ? (
        <View className="card summary-card error-card">
          <Text>{error}</Text>
          <Button className="button-secondary retry-button" onClick={bootstrapDashboard}>
            重试
          </Button>
        </View>
      ) : null}

      <View className="summary-grid">
        <View className="card stat-card">
          <Text className="stat-number">{concepts.length || mastery.length}</Text>
          <Text className="stat-label">知识点</Text>
        </View>
        <View className="card stat-card">
          <Text className="stat-number">{weakConceptCount || memory.weak_points?.length || 0}</Text>
          <Text className="stat-label">薄弱点</Text>
        </View>
        <View className="card stat-card">
          <Text className="stat-number">{untestedConceptCount}</Text>
          <Text className="stat-label">待检测</Text>
        </View>
      </View>

      {learningCenter?.next_move || suggestedConcepts[0] ? (
        <View className="card section-card next-card">
          <Text className="section-title">下一步建议</Text>
          <Text className="next-title">{nextConcept?.concept_name || learningCenter?.next_move?.concept_name || suggestedConcepts[0]?.concept_name}</Text>
          <Text className="next-desc">{learningCenter?.next_move?.reason || "优先练还没测过或掌握度较弱的高价值知识点。"}</Text>
          <Button className="button-primary practice-button" onClick={startNextMove}>
            开始定向练习
          </Button>
        </View>
      ) : null}

      <View className="card section-card">
        <Text className="section-title">推荐练习点</Text>
        {suggestedConcepts.map((concept) => (
          <View key={concept.concept_id} className="concept-row" onClick={() => startConceptPractice(concept)}>
            <View>
              <Text className="concept-title">{concept.concept_name}</Text>
              <Text className="concept-path">{concept.subjectName} / {concept.chapterName} / {concept.topicName}</Text>
              <Text className="concept-meta">掌握 {percent(concept.p_mastery)} · 练习 {concept.attempt_count} 次 · {STATUS_LABELS[concept.status] || concept.status}</Text>
            </View>
            <Text className={`mastery-badge ${concept.status}`}>{concept.test_status === "untested" ? "待测" : STATUS_LABELS[concept.status] || concept.status}</Text>
          </View>
        ))}
        {!suggestedConcepts.length ? <Text className="empty-text">暂无可推荐的练习点。</Text> : null}
      </View>

      <View className="card section-card">
        <Text className="section-title">知识架构</Text>
        {(learningCenter?.subjects || []).map((subject) => {
          const subjectOpen = Boolean(expandedSubjectIds[subject.subject_id]);
          return (
            <View key={subject.subject_id} className="tree-subject">
              <View className="tree-header subject" onClick={() => toggleSubject(subject.subject_id)}>
                <View>
                  <Text className="tree-title">{subject.subject_name}</Text>
                  <Text className="tree-meta">掌握 {percent(subject.mastery_score)} · 覆盖 {percent(subject.coverage_ratio)} · 已测 {subject.tested_count} · 待测 {subject.untested_count}</Text>
                </View>
                <Text className="tree-toggle">{subjectOpen ? "收起" : "展开"}</Text>
              </View>
              {subjectOpen ? (
                <View className="tree-children">
                  {subject.chapters.map((chapter) => {
                    const cKey = chapterKey(subject.subject_id, chapter.chapter_id);
                    const chapterOpen = Boolean(expandedChapterIds[cKey]);
                    return (
                      <View key={cKey} className="tree-chapter">
                        <View className="tree-header chapter" onClick={() => toggleChapter(cKey)}>
                          <View>
                            <Text className="tree-title small">{chapter.chapter_name}</Text>
                            <Text className="tree-meta">掌握 {percent(chapter.mastery_score)} · 已测 {chapter.tested_count} · 待测 {chapter.untested_count} · 薄弱 {chapter.weak_count}</Text>
                          </View>
                          <Text className="tree-toggle">{chapterOpen ? "收起" : "展开"}</Text>
                        </View>
                        {chapterOpen ? (
                          <View className="tree-children compact">
                            {chapter.topics.map((topic) => {
                              const tKey = topicKey(subject.subject_id, chapter.chapter_id, topic.topic_id);
                              const topicOpen = Boolean(expandedTopicIds[tKey]);
                              const conceptsToShow = expandedConceptGroups[tKey] ? topic.concepts : topic.concepts.slice(0, 6);
                              return (
                                <View key={tKey} className="tree-topic">
                                  <View className="tree-header topic" onClick={() => toggleTopic(tKey)}>
                                    <View>
                                      <Text className="tree-title tiny">{topic.topic_name}</Text>
                                      <Text className="tree-meta">掌握 {percent(topic.mastery_score)} · 已测 {topic.tested_count}/{topic.concepts.length} · 薄弱 {topic.weak_count}</Text>
                                    </View>
                                    <Text className="tree-toggle">{topicOpen ? "收起" : "展开"}</Text>
                                  </View>
                                  {topicOpen ? (
                                    <View className="concept-tree-list">
                                      {conceptsToShow.map((concept) => (
                                        <View
                                          key={concept.concept_id}
                                          className="tree-concept-row"
                                          onClick={() => startTreeConceptPractice(subject, chapter, topic, concept)}
                                        >
                                          <View>
                                            <Text className="concept-title">{concept.concept_name}</Text>
                                            <Text className="concept-meta">掌握 {percent(concept.p_mastery)} · 练习 {concept.attempt_count} 次 · 题量 {concept.question_count}</Text>
                                          </View>
                                          <Text className={`mastery-badge ${concept.status}`}>{concept.test_status === "untested" ? "待测" : STATUS_LABELS[concept.status] || concept.status}</Text>
                                        </View>
                                      ))}
                                      {topic.concepts.length > 6 ? (
                                        <View className="show-more-row" onClick={() => toggleConceptGroup(tKey)}>
                                          <Text>{expandedConceptGroups[tKey] ? "收起知识点" : `展开全部 ${topic.concepts.length} 个知识点`}</Text>
                                        </View>
                                      ) : null}
                                      {!topic.concepts.length ? <Text className="empty-text">这个主题下暂无知识点。</Text> : null}
                                    </View>
                                  ) : null}
                                </View>
                              );
                            })}
                            {!chapter.topics.length ? <Text className="empty-text">这个章节下暂无主题。</Text> : null}
                          </View>
                        ) : null}
                      </View>
                    );
                  })}
                  {!subject.chapters.length ? <Text className="empty-text">这个科目下暂无章节。</Text> : null}
                </View>
              ) : null}
            </View>
          );
        })}
        {!(learningCenter?.subjects || []).length ? <Text className="empty-text">暂无知识架构数据。</Text> : null}
      </View>

      <View className="card section-card">
        <Text className="section-title">近期主题</Text>
        {(memory.recent_topics || []).slice(0, 6).map((topic) => (
          <Text key={topic} className="tag-item">{topic}</Text>
        ))}
        {!(memory.recent_topics || []).length ? <Text className="empty-text">还没有近期主题。</Text> : null}
      </View>

      <View className="card section-card">
        <Text className="section-title">旧掌握度记录</Text>
        {mastery.slice(0, 6).map((item) => (
          <View key={`${item.subject_id}-${item.knowledge_point}`} className="mastery-row">
            <View>
              <Text className="mastery-title">{item.concept_name || item.knowledge_point}</Text>
              <Text className="mastery-subtitle">练习 {item.attempt_count} 次，正确 {item.correct_count} 次</Text>
            </View>
            <Text className={`mastery-badge ${item.mastery_level}`}>{percent(item.mastery_score)}</Text>
          </View>
        ))}
        {!mastery.length ? <Text className="empty-text">完成几道练习后，这里会出现掌握度。</Text> : null}
      </View>

      <Text className="team-credit">第六组：方励志、周江杰、黄思炜、朱高辉_Agent学习助手</Text>
    </View>
  );
}
