Page({
  onLoad() {
    const token = wx.getStorageSync('la_access_token');
    if (token) {
      wx.switchTab({ url: '/pages/chat/chat' });
    } else {
      wx.reLaunch({ url: '/pages/login/login' });
    }
  }
});
