import type { ReactNode } from "react";
import { useLaunch } from "@tarojs/taro";

import { initializeCloudContainer } from "@/services/api-transport";
import "./app.scss";

export default function App(props: { children: ReactNode }) {
  useLaunch(() => {
    initializeCloudContainer();
  });

  return props.children;
}
