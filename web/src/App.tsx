import { WechatManagementPage } from "./pages/WechatManagementPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout/AppLayout";
import {
  GithubPage,
  MorningReportPage,
  PlansPage,
  ReadingPage,
  SettingsPage,
} from "./pages";

/** 路由表（不自带 Router，便于测试用 MemoryRouter 包裹）。计划管理为默认入口。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<PlansPage />} />
      <Route path="/knowledge" element={<KnowledgePage />} />
      <Route path="/morning" element={<MorningReportPage />} />
      <Route path="/wechat" element={<WechatManagementPage />} />
      <Route path="/plans" element={<PlansPage />} />
      <Route path="/github" element={<GithubPage />} />
      <Route path="/reading" element={<ReadingPage />} />
      <Route path="/cleanup" element={<WechatManagementPage cleanup />} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="*" element={<div className="text-sm text-neutral-500">页面不存在</div>} />
    </Routes>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <AppRoutes />
      </AppLayout>
    </BrowserRouter>
  );
}
