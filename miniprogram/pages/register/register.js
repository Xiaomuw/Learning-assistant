/**
 * register.js
 * 两步注册流程：Step 1 发送验证码；Step 2 完成注册。
 * 注册成功后同样需要从 Set-Cookie 提取 token。
 */
import { sendRegisterCode } from '../../api/index';
import { persistAuthTokensFromHeader } from '../../utils/request';

function getPasswordStrength(pw) {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;
  if (score <= 1) return { score, label: '弱', color: '#b39ddb' };
  if (score <= 3) return { score, label: '中等', color: '#ff9e80' };
  return { score, label: '强', color: '#69f0ae' };
}

Page({
  data: {
    step: 'email',
    email: '',
    code: '',
    displayName: '',
    password: '',
    confirmPassword: '',
    showPassword: false,
    showConfirmPassword: false,
    error: '',
    successMessage: '',
    isSendingCode: false,
    isSubmitting: false,
    cooldownSeconds: 0,
    passwordStrength: { score: 0, label: '', color: '' },
    passwordsMatch: false,
    passwordsMismatch: false
  },

  _cooldownTimer: null,

  onUnload() {
    if (this._cooldownTimer) clearInterval(this._cooldownTimer);
  },

  onInput(e) {
    const { field } = e.currentTarget.dataset;
    let val = e.detail.value;
    if (field === 'code') val = val.replace(/\D/g, '').slice(0, 6);
    const update = { [field]: val, error: '' };
    if (field === 'password') {
      update.passwordStrength = getPasswordStrength(val);
      const confirm = this.data.confirmPassword;
      update.passwordsMatch = confirm.length > 0 && val === confirm;
      update.passwordsMismatch = confirm.length > 0 && val !== confirm;
    }
    if (field === 'confirmPassword') {
      const pw = this.data.password;
      update.passwordsMatch = val.length > 0 && pw === val;
      update.passwordsMismatch = val.length > 0 && pw !== val;
    }
    this.setData(update);
  },

  togglePassword(e) {
    const { field } = e.currentTarget.dataset;
    if (field === 'confirm') {
      this.setData({ showConfirmPassword: !this.data.showConfirmPassword });
    } else {
      this.setData({ showPassword: !this.data.showPassword });
    }
  },

  async handleSendCode() {
    const email = this.data.email.trim().toLowerCase();
    if (!email) { this.setData({ error: '请输入邮箱地址。' }); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      this.setData({ error: '邮箱格式看起来不对，请检查后再试。' }); return;
    }
    this.setData({ isSendingCode: true, error: '', successMessage: '' });
    try {
      const payload = await sendRegisterCode(email);
      this.setData({
        email,
        step: 'complete',
        successMessage: payload.message || '验证码已发送，请查收邮件。',
        cooldownSeconds: payload.resend_after_seconds || 60
      });
      this._startCooldown();
    } catch (err) {
      this.setData({ error: err.message || '验证码发送失败，请稍后重试。' });
    } finally {
      this.setData({ isSendingCode: false });
    }
  },

  _startCooldown() {
    if (this._cooldownTimer) clearInterval(this._cooldownTimer);
    this._cooldownTimer = setInterval(() => {
      const cur = this.data.cooldownSeconds;
      if (cur <= 0) { clearInterval(this._cooldownTimer); return; }
      this.setData({ cooldownSeconds: cur - 1 });
    }, 1000);
  },

  handleResetEmail() {
    this.setData({
      step: 'email', code: '', password: '', confirmPassword: '',
      error: '', successMessage: '', cooldownSeconds: 0
    });
  },

  handleRegister() {
    const { email, code, password, confirmPassword, displayName } = this.data;
    if (!email) { this.setData({ error: '请先输入邮箱并发送验证码。' }); return; }
    if (!/^\d{6}$/.test(code)) { this.setData({ error: '请输入 6 位数字验证码。' }); return; }
    if (displayName.trim().length > 120) { this.setData({ error: '昵称不能超过 120 个字符。' }); return; }
    if (password.trim().length < 8) { this.setData({ error: '密码至少需要 8 位。' }); return; }
    if (password !== confirmPassword) { this.setData({ error: '两次输入的密码不一致。' }); return; }

    this.setData({ isSubmitting: true, error: '' });

    const app = getApp();
    const apiBase = (app && app.globalData.apiBase) || 'http://localhost:8000/api';

    // 同样需要用 wx.request 以捕获 Set-Cookie
    wx.request({
      url: `${apiBase}/auth/register/complete`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        email,
        code,
        password,
        display_name: displayName.trim() || undefined
      },
      success: (res) => {
        this.setData({ isSubmitting: false });
        if (res.statusCode >= 200 && res.statusCode < 300) {
          persistAuthTokensFromHeader(res.header);
          const user = res.data && res.data.user;
          if (user && user.id) {
            wx.setStorageSync('la_user_id', user.id);
            wx.setStorageSync('la_user_email', user.email || '');
            wx.setStorageSync('la_display_name', user.display_name || '');
          }
          wx.showToast({ title: '注册成功', icon: 'success' });
          setTimeout(() => { wx.switchTab({ url: '/pages/chat/chat' }); }, 800);
        } else {
          const errMsg = (res.data && (res.data.detail || res.data.error)) || '注册失败，请稍后重试。';
          this.setData({ error: errMsg });
        }
      },
      fail: () => {
        this.setData({ isSubmitting: false, error: '网络连接失败，请检查网络后重试。' });
      }
    });
  },

  goToLogin() { wx.navigateBack(); }
});
