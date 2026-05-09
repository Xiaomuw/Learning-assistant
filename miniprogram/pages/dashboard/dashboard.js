/**
 * dashboard.js
 *
 * 后端接口：
 *   GET /api/users/{user_id}/memory         → { weak_points, error_count, recent_topics, last_session }
 *   GET /api/users/{user_id}/knowledge/mastery → { user_id, subject_id, items: [...] }
 */
import { fetchUserMemory, fetchKnowledgeMastery } from '../../api/index';

const EMPTY_MEMORY = {
  weak_points: [],
  error_count: {},
  recent_topics: [],
  last_session: ''
};

Page({
  data: {
    memory: EMPTY_MEMORY,
    mastery: [],
    isLoading: true,
    loadError: '',
    totalErrors: 0,
    totalMastered: 0,
    totalLearning: 0,
    totalWeak: 0
  },

  onShow() {
    const userId = wx.getStorageSync('la_user_id');
    if (!userId) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this._loadData(userId);
  },

  async _loadData(userId) {
    this.setData({ isLoading: true, loadError: '' });

    // 先读本地缓存（来自 practice 提交后持久化）
    try {
      const cached = wx.getStorageSync('la_memory');
      if (cached) {
        const totalErrors = Object.values(cached.error_count || {}).reduce((s, n) => s + n, 0);
        this.setData({ memory: cached, totalErrors });
      }
    } catch (e) { /* ignore */ }

    try {
      const [memoryRes, masteryRes] = await Promise.all([
        fetchUserMemory(userId).catch(() => null),
        fetchKnowledgeMastery(userId).catch(() => null)
      ]);

      const memory = memoryRes || EMPTY_MEMORY;
      // 后端 mastery 返回 { user_id, subject_id, items: [...] }
      const masteryItems = (masteryRes && Array.isArray(masteryRes.items)) ? masteryRes.items : [];

      const totalErrors = Object.values(memory.error_count || {}).reduce((s, n) => s + n, 0);
      const totalMastered = masteryItems.filter(m => m.mastery_level === 'mastered').length;
      const totalLearning = masteryItems.filter(m => m.mastery_level === 'learning').length;
      const totalWeak = masteryItems.filter(m => m.mastery_level === 'weak').length;

      // 持久化最新 memory
      wx.setStorageSync('la_memory', memory);

      this.setData({
        memory,
        mastery: masteryItems,
        totalErrors,
        totalMastered,
        totalLearning,
        totalWeak,
        isLoading: false
      });
    } catch (err) {
      this.setData({
        isLoading: false,
        loadError: err.message || '学习数据加载失败，已展示本地缓存。'
      });
    }
  },

  goToChat() { wx.switchTab({ url: '/pages/chat/chat' }); },
  goToPractice() { wx.switchTab({ url: '/pages/practice/practice' }); }
});
