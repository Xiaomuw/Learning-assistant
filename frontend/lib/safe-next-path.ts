/** Accept only same-origin paths; reject URL-parser normalization bypasses. */
export function getSafeNextPath(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || /[\\\u0000-\u0020\u007f]/.test(value)) return "/chat";
  try {
    const base = "https://learning.invalid";
    const url = new URL(value, base);
    const pathname = decodeURIComponent(url.pathname).replace(/\/+$/, "");
    if (url.origin !== base || pathname === "/login" || pathname === "/register") return "/chat";
    return url.pathname + url.search + url.hash;
  } catch {
    return "/chat";
  }
}
