export default defineAppConfig({
  pages: [
    "pages/login/index",
    "pages/chat/index",
    "pages/practice/index",
    "pages/dashboard/index",
    "pages/profile/index"
  ],
  window: {
    backgroundTextStyle: "light",
    navigationBarBackgroundColor: "#ffffff",
    navigationBarTitleText: "学习助手",
    navigationBarTextStyle: "black"
  },
  tabBar: {
    color: "#64748b",
    selectedColor: "#2563eb",
    backgroundColor: "#ffffff",
    borderStyle: "black",
    list: [
      {
        pagePath: "pages/chat/index",
        text: "问答"
      },
      {
        pagePath: "pages/practice/index",
        text: "刷题"
      },
      {
        pagePath: "pages/dashboard/index",
        text: "中心"
      },
      {
        pagePath: "pages/profile/index",
        text: "我的"
      }
    ]
  }
});
