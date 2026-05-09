declare namespace NodeJS {
  interface ProcessEnv {
    TARO_APP_API_BASE?: string;
    TARO_APP_ID?: string;
  }
}

declare const process: {
  env: NodeJS.ProcessEnv;
};
