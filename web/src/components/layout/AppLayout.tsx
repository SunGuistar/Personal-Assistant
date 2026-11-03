import { NavLink } from "react-router-dom";
import {
  BookOpen,
  CalendarCheck,
  LayoutGrid,
  MessageSquareText,
  Newspaper,
  Settings,
  Trash2,
} from "lucide-react";
import { cn } from "../../lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: LayoutGrid },
  { to: "/wechat", label: "微信助手", icon: MessageSquareText },
  { to: "/news", label: "技术资讯", icon: Newspaper },
  { to: "/plans", label: "计划管理", icon: CalendarCheck },
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

export function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col md:flex-row">
      <aside className="border-b border-neutral-200 bg-white md:min-h-screen md:w-52 md:border-b-0 md:border-r">
        <div className="px-4 pb-2 pt-4 text-base font-semibold">Personal Hub</div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:px-3 md:py-2">
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={({ isActive }) => navLinkClass(isActive)}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="whitespace-nowrap">{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-4 md:p-6">{children}</main>
    </div>
  );
}
