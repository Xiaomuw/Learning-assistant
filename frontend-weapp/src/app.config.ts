const appConfig = {
  cloud: true,
  pages: [
    "pages/login/index",
    "pages/chat/index",
    "pages/practice/index",
    "pages/dashboard/index",
    "pages/profile/index"
  ],
  window: {
    backgroundTextStyle: "light",
    navigationBarBackgroundColor: "#FFFDF8",
    navigationBarTitleText: "学习助手",
    navigationBarTextStyle: "black"
  },
  tabBar: {
    color: "#6B7280",
    selectedColor: "#1F2937",
    backgroundColor: "#FFFDF8",
    borderStyle: "black",
    list: [
      {
        pagePath: "pages/chat/index",
        text: "问答",
        iconPath: "assets/icons/chat.png",
        selectedIconPath: "assets/icons/chat-active.png"
      },
      {
        pagePath: "pages/practice/index",
        text: "刷题",
        iconPath: "assets/icons/practice.png",
        selectedIconPath: "assets/icons/practice-active.png"
      },
      {
        pagePath: "pages/dashboard/index",
        text: "中心",
        iconPath: "assets/icons/dashboard.png",
        selectedIconPath: "assets/icons/dashboard-active.png"
      },
      {
        pagePath: "pages/profile/index",
        text: "我的",
        iconPath: "assets/icons/profile.png",
        selectedIconPath: "assets/icons/profile-active.png"
      }
    ]
  }
};

// WeChat app.json supports `cloud`; Taro's AppConfig type does not expose it.
export default defineAppConfig(appConfig as Parameters<typeof defineAppConfig>[0]);
