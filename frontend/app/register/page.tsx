"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  BrainCircuit,
  Check,
  Eye,
  EyeOff,
  KeyRound,
  Mail,
  RotateCcw,
  Sparkles,
  UserRound,
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

function getPasswordStrength(pw: string): { score: number; label: string; color: string } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^A-Za-z0-9]/.test(pw)) score++;

  if (score <= 1) return { score, label: "弱", color: "bg-neo-accent" };
  if (score <= 3) return { score, label: "中等", color: "bg-neo-secondary" };
  return { score, label: "强", color: "bg-neo-green" };
}

export default function RegisterPage() {
  const router = useRouter();
  const { sendRegisterCode, register, isLoading, user } = useAuth();
  const [nextPath, setNextPath] = useState<string | null>(null);
  const [step, setStep] = useState<"email" | "complete">("email");
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [isSendingCode, setIsSendingCode] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [cooldownSeconds, setCooldownSeconds] = useState(0);

  useEffect(() => {
    setNextPath(new URLSearchParams(window.location.search).get("next"));
  }, []);

  useEffect(() => {
    if (cooldownSeconds <= 0) {
      return;
    }

    const timer = window.setInterval(() => {
      setCooldownSeconds((current) => (current > 0 ? current - 1 : 0));
    }, 1000);

    return () => window.clearInterval(timer);
  }, [cooldownSeconds]);

  const strength = useMemo(() => getPasswordStrength(password), [password]);
  const passwordsMatch = confirmPassword.length > 0 && password === confirmPassword;
  const passwordsMismatch = confirmPassword.length > 0 && password !== confirmPassword;

  async function handleSendCode() {
    setError("");
    setSuccessMessage("");

    const trimmedEmail = email.trim().toLowerCase();
    if (!trimmedEmail) {
      setError("请输入邮箱地址。");
      return;
    }

    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError("邮箱格式看起来不对，请检查后再试。");
      return;
    }

    setIsSendingCode(true);
    try {
      const payload = await sendRegisterCode(trimmedEmail);
      setEmail(trimmedEmail);
      setStep("complete");
      setCooldownSeconds(payload.resend_after_seconds);
      setSuccessMessage(payload.message);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : "验证码发送失败，请稍后重试。");
    } finally {
      setIsSendingCode(false);
    }
  }

  function handleResetEmail() {
    setStep("email");
    setVerificationCode("");
    setPassword("");
    setConfirmPassword("");
    setError("");
    setSuccessMessage("");
    setCooldownSeconds(0);
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSuccessMessage("");

    const trimmedEmail = email.trim().toLowerCase();
    const trimmedDisplayName = displayName.trim();
    const normalizedCode = verificationCode.trim();

    if (!trimmedEmail) {
      setError("请先输入邮箱并发送验证码。");
      return;
    }

    if (!/^\d{6}$/.test(normalizedCode)) {
      setError("请输入 6 位数字验证码。");
      return;
    }

    if (trimmedDisplayName.length > 120) {
      setError("昵称不能超过 120 个字符。");
      return;
    }

    if (password.trim().length < 8) {
      setError("密码至少需要 8 位。");
      return;
    }

    if (password !== confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }

    setIsSubmitting(true);
    try {
      await register(trimmedEmail, normalizedCode, password, trimmedDisplayName);
      router.replace(getSafeNextPath(nextPath));
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "注册失败，请稍后重试。"
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

  const loginHref = nextPath
    ? `/login?next=${encodeURIComponent(nextPath)}`
    : "/login";

  return (
    <main className="flex h-full flex-col bg-neo-bg">
      <section className="relative border-b-[3px] border-neo-ink bg-neo-accent px-5 pb-5 pt-8">
        <div className="pointer-events-none absolute right-4 top-3 animate-float-tag text-neo-ink/15">
          <Sparkles size={60} strokeWidth={1.5} />
        </div>
        <div
          className="pointer-events-none absolute left-6 top-5 animate-float-tag text-neo-ink/10"
          style={{ animationDelay: "0.9s" }}
        >
          <BrainCircuit size={32} strokeWidth={1.5} />
        </div>

        <div className="relative z-10">
          <div className="mb-3 inline-flex items-center gap-2 rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 shadow-neo-sm">
            <BookOpen size={14} strokeWidth={2.8} className="text-neo-muted" />
            <span className="text-[11px] font-black uppercase tracking-[0.16em]">
              邮箱注册
            </span>
          </div>

          <h1 className="text-3xl font-black leading-tight tracking-tight">
            先验证邮箱，再创建账号
          </h1>
          <p className="mt-2 text-sm font-bold leading-relaxed text-neo-ink/70">
            验证码发送到你的邮箱，校验通过后才会真正注册成功
          </p>
        </div>
      </section>

      <section className="flex-1 overflow-y-auto px-4 py-5 pb-8">
        <div className="neo-card bg-white p-5">
          <div className="mb-4 flex items-center gap-2 text-[11px] font-black uppercase tracking-[0.18em]">
            <span
              className={`inline-flex h-8 min-w-8 items-center justify-center rounded-full border-[3px] border-neo-ink px-2 ${
                step === "email" ? "bg-neo-secondary" : "bg-neo-ink text-white"
              }`}
            >
              1
            </span>
            <span className="text-neo-ink/40">发送验证码</span>
            <span className="text-neo-ink/30">/</span>
            <span
              className={`inline-flex h-8 min-w-8 items-center justify-center rounded-full border-[3px] border-neo-ink px-2 ${
                step === "complete" ? "bg-neo-muted" : "bg-white"
              }`}
            >
              2
            </span>
            <span className={step === "complete" ? "text-neo-ink" : "text-neo-ink/40"}>
              完成注册
            </span>
          </div>

          <form
            className="space-y-5"
            onSubmit={(event) => {
              if (step === "email") {
                event.preventDefault();
                void handleSendCode();
                return;
              }
              void handleSubmit(event);
            }}
          >
            {step === "email" ? (
              <div className="space-y-5">
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

                <button
                  type="button"
                  onClick={handleSendCode}
                  disabled={isSendingCode}
                  className="neo-button neo-button-accent w-full disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSendingCode ? "正在发送…" : "发送验证码"}
                </button>
              </div>
            ) : (
              <div className="space-y-5">
                <div className="rounded-[24px] border-[3px] border-neo-ink bg-neo-secondary px-4 py-3 shadow-neo-sm">
                  <p className="neo-label mb-1">验证邮箱</p>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-base font-black">{email}</p>
                      <p className="mt-1 text-xs font-bold text-neo-ink/60">
                        验证码有效期 10 分钟，发送后邮箱会暂时锁定
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={handleResetEmail}
                      className="inline-flex items-center gap-1 rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 text-[11px] font-black uppercase tracking-[0.16em] shadow-neo-sm"
                    >
                      <RotateCcw size={12} strokeWidth={2.5} />
                      修改邮箱
                    </button>
                  </div>
                </div>

                <label className="block">
                  <span className="neo-label mb-2 flex items-center gap-2">
                    <Mail size={12} strokeWidth={2.8} />
                    邮箱验证码
                  </span>
                  <input
                    type="text"
                    value={verificationCode}
                    onChange={(event) =>
                      setVerificationCode(event.target.value.replace(/\D/g, "").slice(0, 6))
                    }
                    placeholder="请输入 6 位数字验证码"
                    className="neo-input"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    required
                  />
                  <div className="mt-2 flex items-center justify-between gap-3 text-xs font-bold">
                    <span className="text-neo-ink/50">
                      {cooldownSeconds > 0
                        ? `可在 ${cooldownSeconds} 秒后重新发送`
                        : "如果没收到，可以重新发送验证码"}
                    </span>
                    <button
                      type="button"
                      onClick={handleSendCode}
                      disabled={isSendingCode || cooldownSeconds > 0}
                      className="rounded-full border-[3px] border-neo-ink bg-white px-3 py-1 uppercase tracking-[0.14em] shadow-neo-sm disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {isSendingCode ? "发送中…" : "重新发送"}
                    </button>
                  </div>
                </label>

                <label className="block">
                  <span className="neo-label mb-2 flex items-center gap-2">
                    <UserRound size={12} strokeWidth={2.8} />
                    昵称
                    <span className="font-bold normal-case tracking-normal text-neo-ink/40">
                      （可选）
                    </span>
                  </span>
                  <input
                    type="text"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder="不填则默认使用邮箱前缀"
                    className="neo-input"
                    autoComplete="nickname"
                    maxLength={120}
                  />
                </label>

                <label className="block">
                  <span className="neo-label mb-2 flex items-center gap-2">
                    <KeyRound size={12} strokeWidth={2.8} />
                    设置密码
                  </span>
                  <div className="relative">
                    <input
                      type={showPassword ? "text" : "password"}
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="至少 8 位"
                      className="neo-input pr-12"
                      autoComplete="new-password"
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

                  {password.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="flex gap-1">
                        {[1, 2, 3, 4, 5].map((i) => (
                          <div
                            key={i}
                            className={`h-1.5 flex-1 rounded-full border border-neo-ink/20 transition-colors duration-200 ${
                              i <= strength.score ? strength.color : "bg-neo-ink/10"
                            }`}
                          />
                        ))}
                      </div>
                      <p className="text-[10px] font-bold text-neo-ink/50">
                        密码强度：{strength.label}
                      </p>
                    </div>
                  )}
                </label>

                <label className="block">
                  <span className="neo-label mb-2 flex items-center gap-2">
                    <KeyRound size={12} strokeWidth={2.8} />
                    确认密码
                    {passwordsMatch && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-neo-green px-2 py-0.5 text-[10px] font-black text-neo-ink">
                        <Check size={10} strokeWidth={3} />
                        一致
                      </span>
                    )}
                  </span>
                  <div className="relative">
                    <input
                      type={showConfirmPassword ? "text" : "password"}
                      value={confirmPassword}
                      onChange={(event) => setConfirmPassword(event.target.value)}
                      placeholder="再次输入密码"
                      className="neo-input pr-12"
                      autoComplete="new-password"
                      minLength={8}
                      required
                    />
                    <button
                      type="button"
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 rounded-full p-1 text-neo-ink/50 transition-colors hover:text-neo-ink"
                      tabIndex={-1}
                      aria-label={showConfirmPassword ? "隐藏确认密码" : "显示确认密码"}
                    >
                      {showConfirmPassword ? (
                        <Eye size={18} strokeWidth={2.5} />
                      ) : (
                        <EyeOff size={18} strokeWidth={2.5} />
                      )}
                    </button>
                  </div>
                  {passwordsMismatch && (
                    <p className="mt-2 text-xs font-bold text-neo-accent">
                      两次输入的密码暂时不一致
                    </p>
                  )}
                </label>

                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="neo-button neo-button-accent w-full disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSubmitting ? "正在完成注册…" : "完成注册"}
                </button>
              </div>
            )}

            {successMessage ? (
              <div className="rounded-[24px] border-[3px] border-neo-ink bg-neo-green px-4 py-3 text-sm font-bold text-neo-ink shadow-neo-sm">
                {successMessage}
              </div>
            ) : null}

            {error ? (
              <div className="rounded-[24px] border-[3px] border-neo-ink bg-neo-accent px-4 py-3 text-sm font-bold text-neo-ink shadow-neo-sm">
                {error}
              </div>
            ) : null}
          </form>

          <div className="mt-6 rounded-[24px] border-[3px] border-dashed border-neo-ink bg-neo-bg px-4 py-4">
            <p className="neo-label mb-1">已经有账号？</p>
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-bold text-neo-ink/70">
                直接用邮箱和密码登录就可以继续学习
              </p>
              <Link href={loginHref} className="neo-button neo-button-secondary">
                去登录
                <ArrowRight size={16} strokeWidth={3} />
              </Link>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
