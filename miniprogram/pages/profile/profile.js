/**
 * profile.js
 *
 * 后端接口及响应格式：
 *   GET  /auth/me                              → { user: { id, email, display_name } }
 *   GET  /users/{id}/profile                   → { user_id, display_name, agent_style_name, agent_style_prompt, onboarding_completed }
 *   PUT  /users/{id}/profile                   → 同上
 *   GET  /subjects                             → [ { id, name, icon, description, doc_count, ... } ]
 *   GET  /users/{id}/sessions                  → [ { id, user_id, subject_id, title, messages, session_memory, updated_at } ]
 *   DELETE /users/{id}/sessions/{session_id}   → { message: '...' }
 *   GET  /users/{id}/practice/recommendations  → { subject_id, items: [...] }
 *   POST /auth/change-password                 → { user: {...} }
 *   POST /auth/logout                          → { message: '...' }
 */
import {
  fetchCurrentUser,
  fetchUserProfile,
  updateUserProfile,
  fetchNotebooks,
  fetchSessions,
  fetchPracticeRecommendations,
  deleteSession,
  changePassword,
  logoutSession
} from '../../api/index';

Page({
  data: {
    user: null,
    profile: null,
    notebooks: [],
    sessions: [],
    recommendedPractice: [],
    isLoading: true,
    notice: null,
    // Edit profile
    showEditProfile: false,
    draftDisplayName: '',
    isSavingDisplayName: false,
    // Change password
    showSecuritySettings: false,
    currentPassword: '',
    newPassword: '',
    confirmNewPassword: '',
    isChangingPassword: false,
    // History
    showHistoryManager: false,
    deletingSessionId: null
  },

  onShow() {
    const userId = wx.getStorageSync('la_user_id');
    if (!userId) {
      wx.reLaunch({ url: '/pages/login/login' });
      return;
    }
    this._loadAll(userId);
  },

  async _loadAll(userId) {
    this.setData({ isLoading: true });
    try {
      // 先用 Storage 快速填充基础信息
      const cachedEmail = wx.getStorageSync('la_user_email') || '';
      const cachedName = wx.getStorageSync('la_display_name') || '';
      this.setData({
        user: { id: userId, email: cachedEmail, display_name: cachedName }
      });

      const [profile, notebooks, sessions, practiceRes] = await Promise.all([
        fetchUserProfile(userId).catch(() => null),
        fetchNotebooks().catch(() => []),
        fetchSessions(userId).catch(() => []),
        fetchPracticeRecommendations(userId).catch(() => ({ items: [] }))
      ]);

      this.setData({
        profile,            // { user_id, display_name, agent_style_name, ... }
        notebooks: Array.isArray(notebooks) ? notebooks : [],
        sessions: Array.isArray(sessions) ? sessions : [],
        // 后端返回 { subject_id, items: [...] }
        recommendedPractice: (practiceRes && Array.isArray(practiceRes.items)) ? practiceRes.items : [],
        isLoading: false
      });
    } catch (err) {
      this.setData({ isLoading: false });
    }
  },

  _showNotice(tone, text) {
    this.setData({ notice: { tone, text } });
    setTimeout(() => { this.setData({ notice: null }); }, 3000);
  },

  dismissNotice() { this.setData({ notice: null }); },

  // ─── Display Name ───
  openEditProfile() {
    // profile.display_name 来自后端；如果为空则用 Storage 缓存
    const name = (this.data.profile && this.data.profile.display_name) ||
                 wx.getStorageSync('la_display_name') || '';
    this.setData({ showEditProfile: true, draftDisplayName: name });
  },
  closeEditProfile() { this.setData({ showEditProfile: false }); },
  onDraftNameInput(e) { this.setData({ draftDisplayName: e.detail.value }); },
  async saveDisplayName() {
    const nextName = this.data.draftDisplayName.trim();
    if (!nextName) { this._showNotice('error', '昵称不能为空。'); return; }
    const userId = wx.getStorageSync('la_user_id');
    this.setData({ isSavingDisplayName: true });
    try {
      // PUT /users/{id}/profile 接收 { display_name, agent_style_name, agent_style_prompt, onboarding_completed }
      const next = await updateUserProfile(userId, { display_name: nextName });
      wx.setStorageSync('la_display_name', next.display_name || nextName);
      this.setData({ profile: next, showEditProfile: false });
      this._showNotice('success', `已更新昵称为「${next.display_name}」`);
    } catch (err) {
      this._showNotice('error', err.message || '保存失败，请稍后重试。');
    } finally {
      this.setData({ isSavingDisplayName: false });
    }
  },

  // ─── Change Password ───
  toggleSecuritySettings() { this.setData({ showSecuritySettings: !this.data.showSecuritySettings }); },
  onPasswordInput(e) { this.setData({ [e.currentTarget.dataset.field]: e.detail.value }); },
  async handleChangePassword() {
    const { currentPassword, newPassword, confirmNewPassword } = this.data;
    if (!currentPassword || !newPassword || !confirmNewPassword) {
      this._showNotice('error', '请把当前密码、新密码和确认密码都填完整。'); return;
    }
    if (newPassword.length < 8) { this._showNotice('error', '新密码至少需要 8 位。'); return; }
    if (newPassword !== confirmNewPassword) { this._showNotice('error', '两次输入的新密码不一致。'); return; }
    this.setData({ isChangingPassword: true });
    try {
      await changePassword(currentPassword, newPassword);
      this.setData({ currentPassword: '', newPassword: '', confirmNewPassword: '' });
      this._showNotice('success', '密码已更新，当前登录态也已同步刷新。');
    } catch (err) {
      this._showNotice('error', err.message || '修改密码失败。');
    } finally {
      this.setData({ isChangingPassword: false });
    }
  },

  // ─── Sessions ───
  toggleHistoryManager() { this.setData({ showHistoryManager: !this.data.showHistoryManager }); },

  deleteSessionItem(e) {
    const { id } = e.currentTarget.dataset;
    const userId = wx.getStorageSync('la_user_id');
    wx.showModal({
      title: '删除聊天记录',
      content: '确定删除这条聊天记录吗？删除后无法恢复。',
      success: async (res) => {
        if (!res.confirm) return;
        this.setData({ deletingSessionId: id });
        try {
          // DELETE /users/{user_id}/sessions/{session_id}
          await deleteSession(userId, id);
          const sessions = this.data.sessions.filter(s => s.id !== id);
          this.setData({ sessions, deletingSessionId: null });
          this._showNotice('success', '聊天记录已删除。');
        } catch (err) {
          this.setData({ deletingSessionId: null });
          this._showNotice('error', err.message || '删除失败，请稍后重试。');
        }
      }
    });
  },

  // 跳转到该会话的聊天（复用 session_id）
  resumeSession(e) {
    const { id } = e.currentTarget.dataset;
    wx.setStorageSync('la_current_session_id', id);
    wx.switchTab({ url: '/pages/chat/chat' });
  },

  // ─── Practice ───
  startRecommendedPractice() {
    const items = this.data.recommendedPractice;
    if (!items.length) return;
    wx.setStorageSync('la_quiz', items);
    wx.switchTab({ url: '/pages/practice/practice' });
  },

  // ─── Logout ───
  handleLogout() {
    wx.showModal({
      title: '退出账号',
      content: '确定退出当前账号吗？退出后会返回登录页。',
      success: async (res) => {
        if (!res.confirm) return;
        try { await logoutSession(); } catch (e) { /* ignore */ }
        wx.removeStorageSync('la_access_token');
        wx.removeStorageSync('la_refresh_token');
        wx.removeStorageSync('la_user_id');
        wx.removeStorageSync('la_user_email');
        wx.removeStorageSync('la_display_name');
        wx.removeStorageSync('la_current_session_id');
        wx.reLaunch({ url: '/pages/login/login' });
      }
    });
  }
});
