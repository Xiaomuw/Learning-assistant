import { redirect } from "next/navigation";

/**
 * 首页 — 直接重定向到 /chat
 */
export default function HomePage() {
  redirect("/chat");
}
