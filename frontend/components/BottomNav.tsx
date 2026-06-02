"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavItem {
  href: string;
  icon: string;
  activeIcon: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "/chat",
    icon: "/weapp-icons/chat.png",
    activeIcon: "/weapp-icons/chat-active.png",
    label: "问答",
  },
  {
    href: "/practice",
    icon: "/weapp-icons/practice.png",
    activeIcon: "/weapp-icons/practice-active.png",
    label: "刷题",
  },
  {
    href: "/dashboard",
    icon: "/weapp-icons/dashboard.png",
    activeIcon: "/weapp-icons/dashboard-active.png",
    label: "中心",
  },
  {
    href: "/profile",
    icon: "/weapp-icons/profile.png",
    activeIcon: "/weapp-icons/profile-active.png",
    label: "我的",
  },
];

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-1/2 z-50 w-full max-w-md -translate-x-1/2 border-t-[3px] border-neo-ink bg-neo-bg safe-area-bottom">
      <div className="grid h-[64px] grid-cols-4 items-center">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname === item.href;

          return (
            <Link
              key={item.href}
              href={item.href}
              aria-label={item.label}
              className={`flex h-full flex-col items-center justify-center gap-1 text-[11px] font-black transition-colors duration-150 ${
                isActive
                  ? "text-[#1F2937]"
                  : "text-[#6B7280] hover:text-[#1F2937]"
              }`}
            >
              <Image
                src={isActive ? item.activeIcon : item.icon}
                alt=""
                width={27}
                height={27}
                className="h-[27px] w-[27px]"
                priority={isActive}
              />
              <span className="leading-none">
                {item.label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
