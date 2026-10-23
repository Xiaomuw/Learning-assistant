"use client";

import Link from "next/link";
import { getSafeNextPath } from "@/lib/safe-next-path";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { ArrowRight, Eye, EyeOff, KeyRound, Mail, Sparkles } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";


function LoginForm() {
  const router = useRouter();
  const { login, isLoading, user } = useAuth();
  const nextPath = useSearchParams().get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);


  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) { setError("请输入邮箱地址。"); return; }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) { setError("邮箱格式看起来不对，请检查后再试。"); return; }
    if (password.trim().length < 8) { setError("密码至少需要 8 位。"); return; }
    setIsSubmitting(true);
    try {
      await login(trimmedEmail, password);
      router.replace(getSafeNextPath(nextPath));
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "登录失败，请稍后重试。");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (isLoading || user) {
    return (
      <div className="flex h-full items-center justify-center bg-neo-bg px-4 sm:px-6">
        <div className="neo-card-secondary w-full max-w-sm p-4 sm:p-6 text-center animate-fade-in">
          <div className="mx-auto mb-3 flex h-10 w-10 sm:h-12 sm:w-12 animate-spin items-center justify-center rounded-full border-2 sm:border-[3px] border-neo-ink border-t-transparent" />
          <p className="text-base sm:text-lg font-black">正在检查登录状态…</p>
        </div>
      </div>
    );
  }

  const registerHref = nextPath ? `/register?next=${encodeURIComponent(nextPath)}` : "/register";

  return (
    <main className="flex h-full flex-col bg-neo-bg">
      {/* ─── Hero ─── */}
      <section className="border-b-2 sm:border-b-[3px] border-neo-ink bg-neo-secondary px-4 sm:px-5 pb-5 sm:pb-6 pt-8 sm:pt-10 safe-area-top animate-fade-in">
        <div className="mb-2 sm:mb-3 inline-flex items-center gap-1.5 sm:gap-2 rounded-full border-2 sm:border-[3px] border-neo-ink bg-white px-2.5 sm:px-3 py-0.5 sm:py-1 shadow-neo-xs sm:shadow-neo-sm">
          <Sparkles size={12} strokeWidth={2.8} className="text-neo-accent sm:hidden" />
          <Sparkles size={14} strokeWidth={2.8} className="text-neo-accent hidden sm:block" />
          <span className="text-[10px] sm:text-[11px] font-black uppercase tracking-[0.14em] sm:tracking-[0.16em]">AI 学习助手</span>
        </div>
        <h1 className="text-2xl sm:text-3xl font-black leading-tight tracking-tight">欢迎回来 👋</h1>
        <p className="mt-1.5 sm:mt-2 text-[13px] sm:text-sm font-bold leading-relaxed text-neo-ink/70">登录你的账号，继续你的学习旅程</p>
        <div className="mt-3 sm:mt-4 flex flex-wrap gap-1.5 sm:gap-2">
          <span className="neo-badge bg-white">📚 智能问答</span>
          <span className="neo-badge bg-white">✏️ 练习刷题</span>
          <span className="neo-badge bg-white">📊 学习追踪</span>
        </div>
      </section>

      {/* ─── Form ─── */}
      <section className="flex-1 overflow-y-auto px-3 sm:px-4 py-4 sm:py-5 pb-6 sm:pb-8">
        <div className="neo-card bg-white p-4 sm:p-5 animate-slide-up">
          <form className="space-y-4 sm:space-y-5" onSubmit={handleSubmit}>
            <label className="block">
              <span className="neo-label mb-1.5 sm:mb-2 flex items-center gap-1.5 sm:gap-2">
                <Mail size={12} strokeWidth={2.8} /> 邮箱地址
              </span>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className="neo-input" autoComplete="email" required />
            </label>

            <label className="block">
              <span className="neo-label mb-1.5 sm:mb-2 flex items-center gap-1.5 sm:gap-2">
                <KeyRound size={12} strokeWidth={2.8} /> 密码
              </span>
              <div className="relative">
                <input type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="至少 8 位" className="neo-input pr-12" autoComplete="current-password" minLength={8} required />
                <button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-neo-ink/50 hover:text-neo-ink" tabIndex={-1}>
                  {showPassword ? <Eye size={18} strokeWidth={2.5} /> : <EyeOff size={18} strokeWidth={2.5} />}
                </button>
              </div>
            </label>

            {error ? (
              <div className="rounded-xl sm:rounded-2xl border-2 sm:border-[3px] border-neo-ink bg-neo-accent p-2.5 sm:p-3 shadow-neo-xs sm:shadow-neo-sm animate-slide-up">
                <p className="text-[13px] sm:text-sm font-bold leading-relaxed">{error}</p>
              </div>
            ) : null}

            <button type="submit" disabled={isSubmitting} className="neo-button w-full justify-center gap-2 py-3 sm:py-4 text-sm sm:text-base">
              {isSubmitting ? (<><div className="h-4 w-4 animate-spin rounded-full border-2 border-neo-ink border-t-transparent" /> 登录中…</>) : (<>立即登录 <ArrowRight size={16} strokeWidth={2.8} className="sm:hidden" /><ArrowRight size={18} strokeWidth={2.8} className="hidden sm:block" /></>)}
            </button>
          </form>

          <div className="my-4 sm:my-5 flex items-center gap-3 sm:gap-4">
            <div className="h-[2px] sm:h-[3px] flex-1 bg-neo-ink/10" />
            <span className="text-[10px] sm:text-[11px] font-black uppercase tracking-widest text-neo-ink/40">OR</span>
            <div className="h-[2px] sm:h-[3px] flex-1 bg-neo-ink/10" />
          </div>

          <Link href={registerHref} className="neo-button-ghost w-full justify-center gap-2 py-3 sm:py-4 text-sm sm:text-base safe-area-bottom">
            创建新账号 <ArrowRight size={16} strokeWidth={2.8} className="sm:hidden" /><ArrowRight size={18} strokeWidth={2.8} className="hidden sm:block" />
          </Link>
        </div>
      </section>
    </main>
  );
}

export default function LoginPage() {
  return <Suspense fallback={<p role="status">正在加载…</p>}><LoginForm /></Suspense>;
}
