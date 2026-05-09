/**
 * login.js
 * 从 Set-Cookie 响应头手动提取 la_access_token / la_refresh_token 并持久化。
 * 后端在登录成功后通过 Set-Cookie 下发 HttpOnly Token。
 */
import { loginWithPassword } from '../../api/index';
import { persistAuthTokensFromHeader } from '../../utils/request';

Page({
  data: {
    email: '',
    password: '',
    showPassword: false,
    error: '',
    isSubmitting: false
  },

  onInput(e) {
    const { field } = e.currentTarget.dataset;
    this.setData({ [field]: e.detail.value, error: '' });
  },

  togglePassword() {
    this.setData({ showPassword: !this.data.showPassword });
  },

  validateEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  },

  handleLogin() {
    const { email, password } = this.data;
    const trimmedEmail = email.trim().toLowerCase();

    if (!trimmedEmail) { this.setData({ error: '请输入邮箱地址。' }); return; }
    if (!this.validateEmail(trimmedEmail)) { this.setData({ error: '邮箱格式看起来不对，请检查后再试。' }); return; }
    if (password.trim().length < 8) { this.setData({ error: '密码至少需要 8 位。' }); return; }

    this.setData({ isSubmitting: true, error: '' });

    // 直接用 wx.request 以便获取完整的响应 header（用于提取 Set-Cookie）
    const app = getApp();
    const apiBase = (app && app.globalData.apiBase) || 'http://localhost:8000/api';

    wx.request({
      url: `${apiBase}/auth/login`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { email: trimmedEmail, password },
      success: (res) => {
        this.setData({ isSubmitting: false });
        if (res.statusCode >= 200 && res.statusCode < 300) {
          // 从响应 header 提取并持久化 Token
          persistAuthTokensFromHeader(res.header);

          // 持久化 user_id
          const user = res.data && res.data.user;
          if (user && user.id) {
            wx.setStorageSync('la_user_id', user.id);
            wx.setStorageSync('la_user_email', user.email || '');
            wx.setStorageSync('la_display_name', user.display_name || '');
          }

          wx.showToast({ title: '登录成功', icon: 'success' });
          setTimeout(() => {
            wx.switchTab({ url: '/pages/chat/chat' });
          }, 800);
        } else {
          const errMsg = (res.data && (res.data.detail || res.data.error)) || '登录失败，请稍后重试。';
          this.setData({ error: errMsg });
        }
      },
      fail: (err) => {
        this.setData({ isSubmitting: false, error: '网络连接失败，请检查网络后重试。' });
      }
    });
  },

  goToRegister() {
    wx.navigateTo({ url: '/pages/register/register' });
  }
});
