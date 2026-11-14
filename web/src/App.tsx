import { WechatManagementPage } from "./pages/WechatManagementPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout/AppLayout";
import { ModuleGate, StartupProvider } from "./components/ModuleGate";
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
    <StartupProvider><Routes>
      <Route path="/" element={<PlansPage />} />
      <Route path="/knowledge" element={<KnowledgePage />} />
      <Route path="/morning" element={<ModuleGate module="morning"><MorningReportPage /></ModuleGate>} />
      <Route path="/wechat" element={<ModuleGate module="wechat"><WechatManagementPage /></ModuleGate>} />
      <Route path="/plans" element={<PlansPage />} />
      <Route path="/github" element={<ModuleGate module="github"><GithubPage /></ModuleGate>} />
      <Route path="/reading" element={<ModuleGate module="reading"><ReadingPage /></ModuleGate>} />
      <Route path="/cleanup" element={<ModuleGate module="wechat"><WechatManagementPage cleanup /></ModuleGate>} />
      <Route path="/settings" element={<SettingsPage />} />
      <Route path="*" element={<div className="text-sm text-neutral-500">页面不存在</div>} />
    </Routes></StartupProvider>
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
