"use client";

import {
  useCallback,
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  completeRegisterWithPassword,
  fetchCurrentUser,
  loginWithPassword,
  logoutSession,
  sendRegisterCode as requestRegisterCode,
  type AuthUser,
  type RegisterCodeResponse,
} from "@/lib/api";
import { clearLearningStore, setLearningStoreUser } from "@/lib/learning-store";

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<AuthUser>;
  sendRegisterCode: (email: string) => Promise<RegisterCodeResponse>;
  register: (
    email: string,
    code: string,
    password: string,
    displayName?: string
  ) => Promise<AuthUser>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<AuthUser | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const AUTH_PAGES = new Set(["/login", "/register"]);
const PROTECTED_PREFIXES = ["/chat", "/practice", "/dashboard", "/profile"];
const AUTH_USER_SNAPSHOT_KEY = "learning_auth_user";
const AUTH_BOOTSTRAP_TIMEOUT_MS = 5000;

function isBrowser() {
  return typeof window !== "undefined";
}

function loadStoredAuthUser(): AuthUser | null {
  if (!isBrowser()) {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_USER_SNAPSHOT_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as Partial<AuthUser>;
    if (
      typeof parsed.id !== "string" ||
      typeof parsed.email !== "string" ||
      typeof parsed.display_name !== "string"
    ) {
      return null;
    }

    return {
      id: parsed.id,
      email: parsed.email,
      display_name: parsed.display_name,
    };
  } catch {
    return null;
  }
}

function persistStoredAuthUser(user: AuthUser | null) {
  if (!isBrowser()) {
    return;
  }

  if (!user) {
    window.localStorage.removeItem(AUTH_USER_SNAPSHOT_KEY);
    return;
  }

  window.localStorage.setItem(AUTH_USER_SNAPSHOT_KEY, JSON.stringify(user));
}

function isProtectedPath(pathname: string) {
  return pathname === "/" || PROTECTED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function getSafeNextPath(nextPath: string | null): string {
  if (!nextPath || !nextPath.startsWith("/") || nextPath.startsWith("//")) {
    return "/chat";
  }

  const [pathname] = nextPath.split("?");
  if (AUTH_PAGES.has(pathname)) {
    return "/chat";
  }

  return nextPath;
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const performUserRefresh = useCallback(async (
    options: { fallbackUser?: AuthUser | null } = {}
  ) => {
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    try {
      const payload = await Promise.race([
        fetchCurrentUser(),
        new Promise<never>((_, reject) => {
          timeoutId = setTimeout(() => {
            reject(new Error("AUTH_RESTORE_TIMEOUT"));
          }, AUTH_BOOTSTRAP_TIMEOUT_MS);
        }),
      ]);

      setUser(payload.user);
      persistStoredAuthUser(payload.user);
      return payload.user;
    } catch (error) {
      if (
        error instanceof Error &&
        error.message === "AUTH_RESTORE_TIMEOUT" &&
        options.fallbackUser
      ) {
        setUser(options.fallbackUser);
        return options.fallbackUser;
      }

      setUser(null);
      setLearningStoreUser(null);
      persistStoredAuthUser(null);
      return null;
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }
  }, []);

  useEffect(() => {
    let active = true;

    async function bootstrap() {
      setIsLoading(true);
      const cachedUser = loadStoredAuthUser();

      if (active && cachedUser) {
        setUser(cachedUser);
        setIsLoading(false);
      }

      const nextUser = await performUserRefresh({ fallbackUser: cachedUser });
      if (!active) {
        return;
      }

      if (nextUser || !cachedUser) {
        setUser(nextUser);
      }
      setIsLoading(false);
    }

    void bootstrap();
    return () => {
      active = false;
    };
  }, [performUserRefresh]);

  useEffect(() => {
    const currentUserId = user?.id ?? null;
    setLearningStoreUser(currentUserId);
  }, [user]);

  const refreshUser = useCallback(() => performUserRefresh(), [performUserRefresh]);

  useEffect(() => {
    if (isLoading) {
      return;
    }

    const currentSearch =
      typeof window !== "undefined" ? window.location.search : "";
    const nextParam =
      typeof window !== "undefined"
        ? new URLSearchParams(window.location.search).get("next")
        : null;
    const currentTarget = `${pathname}${currentSearch}`;

    if (!user && isProtectedPath(pathname)) {
      clearLearningStore();
      router.replace(`/login?next=${encodeURIComponent(currentTarget)}`);
      return;
    }

    if (user && AUTH_PAGES.has(pathname)) {
      router.replace(getSafeNextPath(nextParam));
    }
  }, [isLoading, pathname, router, user]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isLoading,
      async login(email: string, password: string) {
        const payload = await loginWithPassword(email, password);
        clearLearningStore();
        setLearningStoreUser(payload.user.id);
        persistStoredAuthUser(payload.user);
        setUser(payload.user);
        return payload.user;
      },
      async sendRegisterCode(email: string) {
        return requestRegisterCode(email);
      },
      async register(email: string, code: string, password: string, displayName?: string) {
        const payload = await completeRegisterWithPassword(
          email,
          code,
          password,
          displayName
        );
        clearLearningStore();
        setLearningStoreUser(payload.user.id);
        persistStoredAuthUser(payload.user);
        setUser(payload.user);
        return payload.user;
      },
      async logout() {
        try {
          await logoutSession();
        } finally {
          clearLearningStore();
          setLearningStoreUser(null);
          persistStoredAuthUser(null);
          setUser(null);
          router.replace("/login");
        }
      },
      refreshUser,
    }),
    [isLoading, refreshUser, router, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth 必须在 AuthProvider 中使用");
  }
  return value;
}
