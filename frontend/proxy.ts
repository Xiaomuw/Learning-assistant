import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

const PROTECTED_PREFIXES = ["/", "/chat", "/practice", "/dashboard", "/profile"];

function isProtectedPath(pathname: string) {
  if (pathname === "/") {
    return true;
  }
  return PROTECTED_PREFIXES.some(
    (prefix) => prefix !== "/" && pathname.startsWith(prefix)
  );
}

export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasAuthCookie =
    Boolean(request.cookies.get("la_access_token")?.value) ||
    Boolean(request.cookies.get("la_refresh_token")?.value);

  if (isProtectedPath(pathname) && !hasAuthCookie) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/", "/login", "/register", "/chat/:path*", "/practice/:path*", "/dashboard/:path*", "/profile/:path*"],
};
