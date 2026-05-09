import { request } from '../utils/request';

// ============================================================
// Auth — 登录 / 注册 / 当前用户
// ============================================================

export const fetchCurrentUser = () => request('/auth/me');

export const loginWithPassword = (email, password) =>
  request('/auth/login', { method: 'POST', data: { email, password } });

export const sendRegisterCode = (email) =>
  request('/auth/register/send-code', { method: 'POST', data: { email } });

export const completeRegisterWithPassword = (email, code, password, displayName) =>
  request('/auth/register/complete', {
    method: 'POST',
    data: { email, code, password, display_name: displayName || undefined }
  });

export const registerWithPassword = completeRegisterWithPassword;

export const logoutSession = () =>
  request('/auth/logout', { method: 'POST' });

export const changePassword = (currentPassword, newPassword) =>
  request('/auth/change-password', {
    method: 'POST',
    data: { current_password: currentPassword, new_password: newPassword }
  });

// ============================================================
// Notebooks — 笔记本管理
// ============================================================

// GET /subjects  列出所有笔记本
export const fetchNotebooks = () => request('/subjects');

// POST /subjects  创建笔记本
export const createNotebook = (name, icon, description) =>
  request('/subjects', {
    method: 'POST',
    data: { name, icon: icon || null, description: description || null }
  });

// PUT /subjects/{id}  更新笔记本
export const updateNotebook = (subjectId, name, icon, description) =>
  request(`/subjects/${subjectId}`, {
    method: 'PUT',
    data: { name, icon: icon || null, description: description || null }
  });

// DELETE /subjects/{id}  删除笔记本
export const deleteNotebook = (subjectId) =>
  request(`/subjects/${subjectId}`, { method: 'DELETE' });

// GET /subjects/{id}/knowledge/status  知识库状态
export const fetchNotebookKnowledgeStatus = (notebookId) =>
  request(`/subjects/${notebookId}/knowledge/status`);

// POST /subjects/{id}/generate  AI 生成知识库
export const generateNotebookKnowledgeBase = (subjectId) =>
  request(`/subjects/${subjectId}/generate`, { method: 'POST' });

// ============================================================
// User Data — 记忆 / 练习 / 会话 / 掌握度 / 画像
// ============================================================

export const fetchUserMemory = (userId) =>
  request(`/users/${userId}/memory`);

export const fetchKnowledgeMastery = (userId, notebookId) => {
  const suffix = notebookId ? `?subject_id=${notebookId}` : '';
  return request(`/users/${userId}/knowledge/mastery${suffix}`);
};

export const fetchUserProfile = (userId) =>
  request(`/users/${userId}/profile`);

export const updateUserProfile = (userId, payload) =>
  request(`/users/${userId}/profile`, { method: 'PUT', data: payload });

export const fetchSessions = (userId) =>
  request(`/users/${userId}/sessions`);

export const deleteSession = (userId, sessionId) =>
  request(`/users/${userId}/sessions/${sessionId}`, { method: 'DELETE' });

export const fetchLatestQuizBundle = (userId) =>
  request(`/users/${userId}/quiz/latest`);

export const fetchPracticeRecommendations = (userId, notebookId) => {
  const suffix = notebookId ? `?subject_id=${notebookId}` : '';
  return request(`/users/${userId}/practice/recommendations${suffix}`);
};

export const submitPracticeAttempt = (payload) =>
  request('/practice/attempts', {
    method: 'POST',
    data: {
      user_id: payload.user_id,
      session_id: payload.session_id,
      subject_id: payload.notebookId,
      quiz_item: payload.quiz_item,
      selected_option: payload.selected_option
    }
  });

// ============================================================
// Model Config — 模型设置
// ============================================================

export const fetchModelConfig = () => request('/settings/model');
export const updateModelConfig = (chatModel) =>
  request('/settings/model', { method: 'PUT', data: { chat_model: chatModel } });
export const fetchModelHealth = () => request('/settings/model/health');

/**
 * 上传 PDF 到指定笔记本
 * POST /api/upload — multipart/form-data
 * 注意：小程序没有 FormData，需要使用 wx.uploadFile
 */
export const uploadPDFToNotebook = (filePath, notebookId) => {
  return new Promise((resolve, reject) => {
    const app = getApp();
    const apiBase = (app && app.globalData.apiBase) || 'http://localhost:8000/api';
    const token = wx.getStorageSync('la_access_token');
    const header = {};
    // 后端通过 Cookie 鉴权（HttpOnly Cookie 名为 la_access_token）
    if (token) {
      header['Cookie'] = `la_access_token=${token}`;
    }
    wx.uploadFile({
      url: `${apiBase}/upload`,
      filePath: filePath,
      name: 'file',
      formData: { subject_id: notebookId || 'general' },
      header,
      success(res) {
        try {
          const data = JSON.parse(res.data);
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(data);
          } else {
            reject(new Error(data.detail || '上传失败'));
          }
        } catch (e) {
          reject(new Error('上传响应解析失败'));
        }
      },
      fail(err) {
        reject(new Error(err.errMsg || '文件上传网络失败'));
      }
    });
  });
};

/**
 * 导入网页 URL 到指定笔记本
 * POST /api/upload/urls — { subject_id, urls: [] }
 */
export const ingestUrls = (notebookId, urls) =>
  request('/upload/urls', {
    method: 'POST',
    data: { subject_id: notebookId, urls }
  });
