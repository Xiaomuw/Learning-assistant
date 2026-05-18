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
    label: "学习中心",
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
    <nav className="fixed inset-x-0 bottom-0 z-50 border-t-[3px] border-neo-ink bg-white">
      <div className="mx-auto flex w-full max-w-md items-center justify-between">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;
          const Icon = item.icon;

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-label={item.label}
              className={`flex flex-1 flex-col items-center justify-center gap-1 py-2 text-[11px] font-black uppercase tracking-widest transition-all duration-100 ${
                isActive
                  ? `${item.tone} text-neo-ink`
                  : "text-neo-ink/50 hover:bg-neo-bg hover:text-neo-ink"
              }`}
            >
              <Icon size={20} strokeWidth={2.8} />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
