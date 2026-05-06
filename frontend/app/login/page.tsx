"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  Eye,
  EyeOff,
  KeyRound,
  Mail,
  Sparkles,
} from "lucide-react";
import { useAuth } from "@/components/AuthProvider";

function getSafeNextPath(nextPath: string | null): string {
  if (!nextPath || !nextPath.startsWith("/") || nextPath.startsWith("//")) {
    return "/chat";
  }

  const [pathname] = nextPath.split("?");
  if (pathname === "/login" || pathname === "/register") {
    return "/chat";
  }

  return nextPath;
}

export default function LoginPage() {
  const router = useRouter();
  const { login, isLoading, user } = useAuth();
  const [nextPath, setNextPath] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setNextPath(new URLSearchParams(window.location.search).get("next"));
  }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");

    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setError("请输入邮箱地址。");
      return;
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError("邮箱格式看起来不对，请检查后再试。");
      return;
    }

    if (password.trim().length < 8) {
      setError("密码至少需要 8 位。");
      return;
    }

    setIsSubmitting(true);

    try {
      await login(trimmedEmail, password);
      router.replace(getSafeNextPath(nextPath));
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "登录失败，请稍后重试。"
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading || user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-6">
        <div className="neo-card-secondary w-full max-w-sm p-6 text-center">
          <div className="mx-auto mb-3 flex h-12 w-12 animate-spin items-center justify-center rounded-full border-[3px] border-neo-ink border-t-transparent" />
          <p className="text-lg font-black">正在检查登录状态…</p>
        </div>
      </div>
    );
  }

  const registerHref = nextPath
    ? `/register?next=${encodeURIComponent(nextPath)}`
    : "/register";

  return (
    <main className="flex h-full flex-col bg-neo-bg">
      {/* ─── Hero Banner ─── */}
      <section className="relative border-b-[3px] border-neo-ink bg-neo-secondary px-5 pb-5 pt-8">
        {/* Floating decorative icons */}
        <div className="pointer-events-none absolute right-4 top-3 animate-float-tag text-neo-ink/15">
          <BrainCircuit size={60} strokeWidth={1.5} />
        </div>
        <div className="pointer-events-none absolute left-6 top-6 animate-float-tag text-neo-ink/10" style={{ animationDelay: "1.2s" }}>
          <BookOpen size={32} strokeWidth={1.5} />
        </div>

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 shadow-neo-sm">
            <Sparkles size={14} strokeWidth={2.8} className="text-neo-accent" />
            <span className="text-[11px] font-black uppercase tracking-[0.16em]">
              AI 学习助手
            </span>
          </div>

          <h1 className="text-3xl font-black leading-tight tracking-tight">
            欢迎回来 👋
          </h1>
          <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
            登录你的账号，继续你的学习旅程
          </p>
        </div>
      </section>

      {/* ─── Form ─── */}
      <section className="flex-1 overflow-y-auto px-4 py-5 pb-8">
        <div className="neo-card bg-white p-5">
          <form className="space-y-5" onSubmit={handleSubmit}>
            {/* Email */}
            <label className="block">
              <span className="neo-label mb-2 flex items-center gap-2">
                <Mail size={12} strokeWidth={2.8} />
                邮箱地址
              </span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                className="neo-input"
                autoComplete="email"
                required
              />
            </label>

            {/* Password */}
            <label className="block">
              <span className="neo-label mb-2 flex items-center gap-2">
                <KeyRound size={12} strokeWidth={2.8} />
                密码
              </span>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="至少 8 位"
                  className="neo-input pr-12"
                  autoComplete="current-password"
                  minLength={8}
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-neo-ink/50 transition-colors hover:text-neo-ink"
                  tabIndex={-1}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                >
                  {showPassword ? (
                    <Eye size={18} strokeWidth={2.5} />
                  ) : (
                    <EyeOff size={18} strokeWidth={2.5} />
                  )}
                </button>
              </div>
            </label>

            {/* Error */}
            {error ? (
              <div className="animate-stamp-in rounded-2xl border-[3px] border-neo-ink bg-neo-accent p-3 shadow-neo-sm">
                <p className="text-sm font-bold leading-relaxed">{error}</p>
              </div>
            ) : null}

            {/* Submit */}
            <button
              type="submit"
              disabled={isSubmitting}
              className="neo-button w-full justify-center gap-2 py-4 text-base"
            >
              {isSubmitting ? (
                <>
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-neo-ink border-t-transparent" />
                  登录中…
                </>
              ) : (
                <>
                  立即登录
                  <ArrowRight size={18} strokeWidth={2.8} />
                </>
              )}
            </button>
          </form>

          {/* Divider */}
          <div className="my-5 flex items-center gap-4">
            <div className="h-[3px] flex-1 bg-neo-ink/10" />
            <span className="text-[11px] font-black uppercase tracking-widest text-neo-ink/40">
              OR
            </span>
            <div className="h-[3px] flex-1 bg-neo-ink/10" />
          </div>

          <div className="mb-4 rounded-[22px] border-[3px] border-dashed border-neo-ink bg-neo-bg px-4 py-3">
            <p className="text-sm font-bold leading-relaxed text-neo-ink/70">
              还没账号？先去邮箱收验证码，再回来继续注册。
            </p>
          </div>

          {/* Register link */}
          <Link
            href={registerHref}
            className="neo-button-ghost w-full justify-center gap-2 py-4 text-base"
          >
            创建新账号
            <ArrowRight size={18} strokeWidth={2.8} />
          </Link>
        </div>


      </section>
    </main>
  );
}
