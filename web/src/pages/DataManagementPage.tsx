import { NavLink } from "react-router-dom";
import { ModuleGate } from "../components/ModuleGate";
import { GithubPage } from "./GithubPage";
import { WechatPage } from "./WechatPage";
import { CleanupPage } from "./CleanupPage";
import { StoragePage } from "./StoragePage";

export function DataManagementPage({ tab = "storage" }: { tab?: "github" | "wechat" | "cleanup" | "storage" }) {
  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">数据管理</h1>
    <nav aria-label="数据管理功能" className="flex flex-wrap gap-2 border-b pb-3">
      {[{to:"/storage", label:"存储浏览"}, {to:"/github", label:"GitHub"}, {to:"/wechat", label:"微信助手"}, {to:"/cleanup", label:"清理审核"}].map(item =>
        <NavLink key={item.to} to={item.to} className={({isActive}) => `rounded-md px-4 py-2 text-sm ${isActive ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-600"}`}>{item.label}</NavLink>)}
    </nav>
    {tab === "storage" ? <StoragePage /> : tab === "github" ? <ModuleGate module="github"><GithubPage /></ModuleGate>
      : <ModuleGate module="wechat">{tab === "cleanup" ? <CleanupPage /> : <WechatPage />}</ModuleGate>}
  </div>;
}
