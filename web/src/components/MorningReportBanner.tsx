import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight } from "lucide-react";

import { useMorningReport } from "../api/morning";

function todayInBeijing(): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai" }).format(new Date());
}

export function MorningReportBanner() {
  const report = useMorningReport();
  const [today, setToday] = useState(todayInBeijing);

  useEffect(() => {
    const timer = window.setInterval(() => setToday(todayInBeijing()), 20000);
    return () => window.clearInterval(timer);
  }, []);

  // 只在查询成功且确认没有今日报告时提示，避免把加载或接口故障误报为未生成。
  if (!report.isSuccess || report.data?.report_date === today) return null;

  return (
    <section role="status" aria-label="今日晨报未生成提醒"
      className="flex items-center gap-5 rounded-xl border-2 border-amber-400 bg-amber-50 px-6 py-6 text-amber-950 shadow-sm">
      <AlertTriangle className="h-10 w-10 shrink-0 text-amber-600" aria-hidden="true" />
      <div className="flex-1">
        <h2 className="text-2xl font-bold">今日晨报尚未生成</h2>
        <p className="mt-2 text-sm text-amber-800">{today} · 前往今日晨报查看进度或手动生成，生成完成后此提示将自动消失。</p>
      </div>
      <Link to="/morning" className="inline-flex shrink-0 items-center gap-2 rounded-lg bg-amber-600 px-5 py-3 font-semibold text-white hover:bg-amber-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700">
        前往今日晨报 <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
    </section>
  );
}
