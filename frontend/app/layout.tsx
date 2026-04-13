import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "学习问答助手 — 多 Agent 智能辅导",
  description:
    "基于多 Agent 架构的智能学习辅导系统，提供概念讲解、解题辅导、智能出题和复习巩固。",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="font-sans bg-neo-bg">
        <div className="mx-auto w-full max-w-md h-[100dvh] bg-neo-bg relative overflow-hidden flex flex-col md:border-x-4 md:border-black md:shadow-[16px_16px_0px_0px_#1e293b]">
          {children}
        </div>
      </body>
    </html>
  );
}
