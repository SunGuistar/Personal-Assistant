import { BrowserRouter, Route, Routes } from "react-router-dom";

import { AppLayout } from "./components/layout/AppLayout";
import {
  CleanupPage,
  HomePage,
  NewsPage,
  PlansPage,
  ReadingPage,
  SettingsPage,
  WechatPage,
} from "./pages";

/** 路由表（不自带 Router，便于测试用 MemoryRouter 包裹）。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/wechat" element={<WechatPage />} />
      <Route path="/news" element={<NewsPage />} />
      <Route path="/plans" element={<PlansPage />} />
      <Route path="/reading" element={<ReadingPage />} />
      <Route path="/cleanup" element={<CleanupPage />} />
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
