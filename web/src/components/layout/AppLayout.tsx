import { useState } from "react";
import { NavLink } from "react-router-dom";
import {
  BookOpen,
  CalendarCheck,
  LayoutGrid,
  MessageSquareText,
  Newspaper,
  PanelRightClose,
  PanelRightOpen,
  Settings,
  Trash2,
} from "lucide-react";
import { cn } from "../../lib/utils";
import { ImportantInfosPanel } from "../rail/ImportantInfosPanel";
import { MemoPanel } from "../rail/MemoPanel";

const NAV_ITEMS = [
  { to: "/", label: "首页", icon: LayoutGrid },
  { to: "/wechat", label: "微信助手", icon: MessageSquareText },
  { to: "/news", label: "技术资讯", icon: Newspaper },
  { to: "/plans", label: "计划管理", icon: CalendarCheck },
  { to: "/reading", label: "阅读管理", icon: BookOpen },
  { to: "/cleanup", label: "清理审核", icon: Trash2 },
  { to: "/settings", label: "设置", icon: Settings },
];

const COLLAPSE_KEY = "hub.rightrail.collapsed";

function navLinkClass(active: boolean) {
  return cn(
    "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
    active ? "bg-neutral-900 text-neutral-50" : "text-neutral-600 hover:bg-neutral-200/60"
  );
}

/**
 * PC 浏览器三栏工作台（本版本仅面向 PC，不做移动端适配）：
 * 左侧导航（192px）+ 中央业务区（flex 自适应 ≥650px，独立滚动）
 * + 右侧常驻信息栏（340px：上部重要信息 ~40% / 下部随手备忘 ~60%，各自独立滚动）。
 * 右侧栏折叠状态存 localStorage；折叠只隐藏宽度、组件保持挂载（编辑内容不丢）。
 */
export function AppLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem(COLLAPSE_KEY) === "1"
  );

  const toggle = () => {
    setCollapsed((value) => {
      localStorage.setItem(COLLAPSE_KEY, value ? "0" : "1");
      return !value;
    });
  };

  return (
    <div className="flex h-screen w-full overflow-hidden bg-neutral-50">
      {/* 左栏：导航 */}
      <aside className="flex w-48 shrink-0 flex-col border-r border-neutral-200 bg-white">
        <div className="px-4 pb-2 pt-4 text-base font-semibold">个人助手</div>
        <nav className="flex flex-col gap-1 px-3 py-2">
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

      {/* 中央：业务工作区（独立纵向滚动） */}
      <main className="min-w-[650px] flex-1 overflow-y-auto p-4">{children}</main>

      {/* 右栏折叠按钮（常驻中央区右缘，折叠/展开均可用） */}
      <button
        onClick={toggle}
        aria-label={collapsed ? "展开右侧栏" : "折叠右侧栏"}
        title={collapsed ? "展开右侧栏" : "折叠右侧栏"}
        className="my-4 ml-1 flex w-5 shrink-0 items-center justify-center rounded-l border border-r-0 border-neutral-200 bg-white text-neutral-400 hover:text-neutral-700"
      >
        {collapsed ? <PanelRightOpen className="h-4 w-4" /> : <PanelRightClose className="h-4 w-4" />}
      </button>

      {/* 右栏：重要信息（上）+ 随手备忘（下）。折叠时保持挂载，仅隐藏宽度。 */}
      <aside
        className={cn(
          "shrink-0 border-l border-neutral-200 bg-neutral-50",
          collapsed ? "hidden" : "flex w-[340px] flex-col"
        )}
      >
        <div className="flex h-full min-h-0 flex-col">
          <ImportantInfosPanel />
          <MemoPanel />
        </div>
      </aside>
    </div>
  );
}
