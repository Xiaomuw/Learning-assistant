import type { Metadata, Viewport } from "next";
import "./globals.css";
import AuthProvider from "@/components/AuthProvider";

export const metadata: Metadata = {
  title: "学习问答助手 — 多 Agent 智能辅导",
  description:
    "基于多 Agent 架构的智能学习辅导系统，提供概念讲解、解题辅导、智能出题和复习巩固。",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="font-sans bg-neo-bg">
        <AuthProvider>
          <div className="mx-auto w-full max-w-md min-h-[100dvh] bg-neo-bg relative overflow-hidden flex flex-col sm:border-x-[3px] sm:border-black sm:shadow-[8px_8px_0px_0px_#1e293b]">
            {children}
          </div>
        </AuthProvider>
      </body>
    </html>
  );
}
