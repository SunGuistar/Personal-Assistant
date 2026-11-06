export { HomePage } from "./HomePage";
export { NewsPage } from "./NewsPage";
export { PlansPage } from "./PlansPage";
export { ReadingPage } from "./ReadingPage";
export { WechatPage } from "./WechatPage";
export { CleanupPage } from "./CleanupPage";

function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">{title}</h1>
      <div className="rounded-lg border border-dashed border-neutral-300 bg-white p-6 text-sm text-neutral-500">
        {note}
      </div>
    </div>
  );
}

export function SettingsPage() {
  return (
    <Placeholder
      title="基础设置"
      note="后续提供：模型配置、WeChatDataAnalysis 路径。当前为占位页。"
    />
  );
}
