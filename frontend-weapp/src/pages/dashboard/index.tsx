import { useState } from "react";
import { useDidShow } from "@tarojs/taro";
import { Button, Text, View } from "@tarojs/components";
import { ensureAuthSession, fetchKnowledgeMastery, fetchUserMemory } from "@/services/api";
import { requireAuthUser } from "@/store/auth";
import { getStoredNotebookId } from "@/store/learning";
import type { KnowledgeMastery, Memory } from "@/types/api";
import "./index.scss";

const EMPTY_MEMORY: Memory = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: ""
};

export default function DashboardPage() {
  const [memory, setMemory] = useState<Memory>(EMPTY_MEMORY);
  const [mastery, setMastery] = useState<KnowledgeMastery[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useDidShow(() => {
    void bootstrapDashboard();
  });

  async function bootstrapDashboard() {
    const ready = await ensureAuthSession();
    if (!ready) return;
    const user = requireAuthUser();
    if (!user) return;
    await loadDashboard(user.id);
  }

  async function loadDashboard(userId: string) {
    setLoading(true);
    setError("");
    try {
      const [memoryPayload, masteryPayload] = await Promise.all([
        fetchUserMemory(userId),
        fetchKnowledgeMastery(userId, getStoredNotebookId())
      ]);
      setMemory(memoryPayload || EMPTY_MEMORY);
      setMastery(Array.isArray(masteryPayload.items) ? masteryPayload.items : []);
    } catch (err: any) {
      setError(err?.message || "学习数据加载失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <View className="page dashboard-page">
      <Text className="page-title">学习中心</Text>
      <Text className="page-subtitle">这里汇总最近学习轨迹和知识点掌握度。</Text>

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
          <Text className="stat-number">{memory.weak_points?.length || 0}</Text>
          <Text className="stat-label">薄弱点</Text>
        </View>
        <View className="card stat-card">
          <Text className="stat-number">{memory.recent_topics?.length || 0}</Text>
          <Text className="stat-label">近期主题</Text>
        </View>
        <View className="card stat-card">
          <Text className="stat-number">{mastery.length}</Text>
          <Text className="stat-label">掌握度记录</Text>
        </View>
      </View>

      <View className="card section-card">
        <Text className="section-title">近期主题</Text>
        {(memory.recent_topics || []).slice(0, 6).map((topic) => (
          <Text key={topic} className="tag-item">{topic}</Text>
        ))}
        {!(memory.recent_topics || []).length ? <Text className="empty-text">还没有近期主题。</Text> : null}
      </View>

      <View className="card section-card">
        <Text className="section-title">薄弱点</Text>
        {(memory.weak_points || []).slice(0, 6).map((point) => (
          <Text key={point} className="tag-item danger">{point}</Text>
        ))}
        {!(memory.weak_points || []).length ? <Text className="empty-text">暂时没有记录到明显薄弱点。</Text> : null}
      </View>

      <View className="card section-card">
        <Text className="section-title">知识点掌握度</Text>
        {mastery.slice(0, 8).map((item) => (
          <View key={`${item.subject_id}-${item.knowledge_point}`} className="mastery-row">
            <View>
              <Text className="mastery-title">{item.knowledge_point}</Text>
              <Text className="mastery-subtitle">练习 {item.attempt_count} 次，正确 {item.correct_count} 次</Text>
            </View>
            <Text className={`mastery-badge ${item.mastery_level}`}>{Math.round((item.mastery_score || 0) * 100)}%</Text>
          </View>
        ))}
        {!mastery.length ? <Text className="empty-text">完成几道练习后，这里会出现掌握度。</Text> : null}
      </View>
    </View>
  );
}
