const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const projectConfigPath = path.join(root, "project.config.json");
const privateConfigPath = path.join(root, "project.private.config.json");
const projectConfig = JSON.parse(fs.readFileSync(projectConfigPath, "utf8"));
const appid = process.env.TARO_APP_ID || process.env.WECHAT_MINI_APP_ID || projectConfig.appid || "touristappid";

const privateConfig = {
  appid,
  projectname: projectConfig.projectname,
  setting: {
    ...projectConfig.setting,
    urlCheck: appid === "touristappid" ? false : projectConfig.setting?.urlCheck
  }
};

fs.writeFileSync(privateConfigPath, `${JSON.stringify(privateConfig, null, 2)}\n`);
console.log(`Prepared project.private.config.json for appid=${appid}`);
