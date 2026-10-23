const apiTransport = process.env.TARO_APP_API_TRANSPORT || "request";
const defaultApiBase = apiTransport === "container" ? "" : "http://127.0.0.1:8000/api";
const chatStreamApiBase = process.env.TARO_APP_CHAT_STREAM_API_BASE
  || process.env.TARO_APP_API_BASE
  || defaultApiBase;

const config = {
  projectName: "learning-assistant-weapp",
  date: "2026-05-08",
  designWidth: 750,
  deviceRatio: {
    640: 2.34 / 2,
    750: 1,
    828: 1.81 / 2
  },
  sourceRoot: "src",
  outputRoot: "dist",
  plugins: [],
  defineConstants: {
    "process.env.TARO_APP_API_BASE": JSON.stringify(
      process.env.TARO_APP_API_BASE || defaultApiBase
    ),
    "process.env.TARO_APP_CHAT_STREAM_API_BASE": JSON.stringify(chatStreamApiBase),
    "process.env.TARO_APP_API_TRANSPORT": JSON.stringify(apiTransport),
    "process.env.TARO_APP_CLOUD_ENV": JSON.stringify(process.env.TARO_APP_CLOUD_ENV || ""),
    "process.env.TARO_APP_CONTAINER_SERVICE": JSON.stringify(
      process.env.TARO_APP_CONTAINER_SERVICE || ""
    ),
    "process.env.TARO_APP_CHAT_DEBUG_PROCESS": JSON.stringify(
      process.env.TARO_APP_CHAT_DEBUG_PROCESS || "false"
    ),
    "process.env.TARO_APP_ID": JSON.stringify(
      process.env.TARO_APP_ID || process.env.WECHAT_MINI_APP_ID || "touristappid"
    )
  },
  copy: {
    patterns: [
      { from: "LICENSE", to: "dist/LICENSE.txt" },
      { from: "LICENSE-SCOPE.md", to: "dist/LICENSE-SCOPE.md" }
    ],
    options: {}
  },
  framework: "react",
  compiler: {
    type: "webpack5",
    prebundle: {
      enable: false
    }
  },
  mini: {
    postcss: {
      pxtransform: {
        enable: true,
        config: {}
      },
      cssModules: {
        enable: false,
        config: {
          namingPattern: "module",
          generateScopedName: "[name]__[local]___[hash:base64:5]"
        }
      }
    },
    webpackChain(chain) {
      chain.resolve.alias.set("@", require("path").resolve(__dirname, "..", "src"));
    }
  },
  h5: {}
};

module.exports = function () {
  return config;
};
