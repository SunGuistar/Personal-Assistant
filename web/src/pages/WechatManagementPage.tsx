import { NavLink } from "react-router-dom";
import { WechatPage } from "./WechatPage";
import { CleanupPage } from "./CleanupPage";

export function WechatManagementPage({ cleanup = false }: { cleanup?: boolean }) {
  return <div className="space-y-4">
    <h1 className="text-xl font-semibold">微信管理</h1>
    <nav aria-label="微信管理功能" className="flex gap-2 border-b pb-3">
      {[{to:"/wechat", label:"微信助手"}, {to:"/cleanup", label:"清理审核"}].map(item => <NavLink key={item.to} to={item.to} className={({isActive}) => `rounded-md px-4 py-2 text-sm ${isActive ? "bg-neutral-900 text-white" : "bg-neutral-100 text-neutral-600"}`}>{item.label}</NavLink>)}
    </nav>
    {cleanup ? <CleanupPage /> : <WechatPage />}
  </div>;
}
