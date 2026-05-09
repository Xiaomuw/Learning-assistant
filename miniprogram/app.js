App({
  onLaunch() {
    // 初始化应用
    // 这里可以放全局共享的数据
    const token = wx.getStorageSync('la_access_token');
    if (!token) {
      // 未登录
      // 如果不是直接启动到登录页，则可能需要处理重定向，但我们用 index/index 做分发
    }
  },
  globalData: {
    userInfo: null,
    apiBase: 'http://localhost:8000/api' // 后端 API 地址，可按需修改
  }
})
