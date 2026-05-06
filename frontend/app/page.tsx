import { cookies } from "next/headers";
import { redirect } from "next/navigation";

/**
 * 首页 — 直接重定向到 /chat
 */
export default function HomePage() {
  const cookieStore = cookies();
  const hasAuthCookie =
    Boolean(cookieStore.get("la_access_token")?.value) ||
    Boolean(cookieStore.get("la_refresh_token")?.value);

  redirect(hasAuthCookie ? "/chat" : "/login");
}
