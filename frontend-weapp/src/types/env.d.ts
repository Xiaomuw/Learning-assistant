declare namespace NodeJS {
  interface ProcessEnv {
    TARO_APP_API_BASE?: string;
    TARO_APP_CHAT_STREAM_API_BASE?: string;
    TARO_APP_API_TRANSPORT?: "request" | "container" | string;
    TARO_APP_CLOUD_ENV?: string;
    TARO_APP_CONTAINER_SERVICE?: string;
    TARO_APP_CHAT_DEBUG_PROCESS?: string;
    TARO_APP_ID?: string;
  }
}

declare const process: {
  env: NodeJS.ProcessEnv;
};
