"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, MessageCircleMore, PencilRuler, User } from "lucide-react";

interface NavItem {
  href: string;
  icon: typeof MessageCircleMore;
  label: string;
  tone: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "/chat",
    icon: MessageCircleMore,
    label: "问答",
    tone: "bg-neo-secondary",
  },
  {
    href: "/practice",
    icon: PencilRuler,
    label: "刷题",
    tone: "bg-neo-accent",
  },
  {
    href: "/dashboard",
    icon: BarChart3,
    label: "中心",
    tone: "bg-neo-muted",
  },
  {
    href: "/profile",
    icon: User,
    label: "我的",
    tone: "bg-neo-accent",
  },
];

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="absolute inset-x-0 bottom-6 z-50 pointer-events-none px-4 flex justify-center">
      <div className="w-full max-w-[380px] pointer-events-auto rounded-[2rem] border-[3px] border-neo-ink bg-white p-2 shadow-neo-sm">
        <div className="flex items-center justify-between gap-1">
          {NAV_ITEMS.map((item) => {
            const isActive = pathname === item.href;
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                aria-label={item.label}
                className={`flex flex-col flex-1 items-center justify-center gap-1 rounded-2xl border-[3px] px-2 py-3 text-[11px] font-black uppercase tracking-widest transition-all duration-100 ease-linear ${
                  isActive
                    ? `${item.tone} border-neo-ink text-neo-ink shadow-neo-sm -translate-y-1`
                    : "border-transparent text-neo-ink/60 hover:bg-neo-bg hover:border-neo-ink hover:text-neo-ink hover:-translate-y-1"
                }`}
              >
                <Icon size={20} strokeWidth={2.8} />
                <span>{item.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
