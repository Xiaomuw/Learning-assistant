const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const projectConfigPath = path.join(root, "project.config.json");
const privateConfigPath = path.join(root, "project.private.config.json");
const projectConfig = JSON.parse(fs.readFileSync(projectConfigPath, "utf8"));
const appid = process.env.TARO_APP_ID || process.env.WECHAT_MINI_APP_ID || projectConfig.appid || "touristappid";
const stableSettingKeys = [
  "urlCheck",
  "es6",
  "enhance",
  "postcss",
  "minified",
  "newFeature",
  "nodeModules",
  "useCompilerPlugins",
  "ignoreUploadUnusedFiles"
];

function pickStableSettings(settings = {}) {
  return stableSettingKeys.reduce((picked, key) => {
    if (Object.prototype.hasOwnProperty.call(settings, key)) {
      picked[key] = settings[key];
    }
    return picked;
  }, {});
}

const privateConfig = {
  appid,
  projectname: projectConfig.projectname,
  libVersion: projectConfig.libVersion || "3.5.0",
  setting: {
    ...pickStableSettings(projectConfig.setting),
    urlCheck: appid === "touristappid" ? false : projectConfig.setting?.urlCheck
  }
};

fs.writeFileSync(privateConfigPath, `${JSON.stringify(privateConfig, null, 2)}\n`);
console.log(`Prepared project.private.config.json for appid=${appid}`);
