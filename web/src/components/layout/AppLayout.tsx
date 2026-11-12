import { NavLink } from "react-router-dom";
import {
  BookOpen,
  CalendarCheck,
  Github,
  MessageSquareText,
  Sunrise,
  Settings,
  Trash2,
} from "lucide-react";
import { cn } from "../../lib/utils";

const NAV_ITEMS = [
  { to: "/plans", label: "计划管理", icon: CalendarCheck },
  { to: "/morning", label: "今日晨报", icon: Sunrise },
  { to: "/wechat", label: "微信助手", icon: MessageSquareText },
  { to: "/github", label: "GitHub", icon: Github },
  { to: "/reading", label: "阅读管理", icon: BookOpen },
  { to: "/cleanup", label: "清理审核", icon: Trash2 },
  { to: "/settings", label: "设置", icon: Settings },
];

function navLinkClass(active: boolean) {
  return cn(
    "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
    active ? "bg-neutral-900 text-neutral-50" : "text-neutral-600 hover:bg-neutral-200/60"
  );
}

/**
 * PC 浏览器两栏工作台（本版本仅面向 PC，不做移动端适配）：
 * 左侧导航（192px）+ 中央业务区（flex 自适应 ≥650px，独立滚动）。
 * 重要信息与随手备忘已从全局右栏移入计划管理页面，不在其他页面展示。
 */
export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen w-full overflow-hidden bg-neutral-50">
      {/* 左栏：导航（计划管理为默认入口） */}
      <aside className="flex w-48 shrink-0 flex-col border-r border-neutral-200 bg-white">
        <div className="px-4 pb-2 pt-4 text-base font-semibold">个人助手</div>
        <nav className="flex flex-col gap-1 px-3 py-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className={({ isActive }) => navLinkClass(isActive)}>
              <Icon className="h-4 w-4 shrink-0" />
              <span className="whitespace-nowrap">{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* 中央：业务工作区（独立纵向滚动） */}
      <main className="min-w-[650px] flex-1 overflow-y-auto p-4">{children}</main>
    </div>
  );
}
