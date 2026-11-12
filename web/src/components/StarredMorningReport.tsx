import { Report, useNewsImportance, useReportNews } from "../api/morning";
import { MorningReportBody } from "./MorningReportBody";

export function StarredMorningReport({ report }: { report: Report }) {
  const news = useReportNews(report.id);
  const mark = useNewsImportance();
  return <>
    {(news.isError || mark.isError) && <p role="alert" className="mb-3 text-sm text-red-600">
      {mark.isError ? "星标保存失败，请重试。" : "新闻星标加载失败，请刷新重试。"}
    </p>}
    <MorningReportBody key={report.id} text={report.content_md} newsSelection={report.sections.news_selection}
      newsItems={news.data?.items} pendingNewsId={mark.isPending ? mark.variables.id : undefined}
      onImportanceChange={(id, is_important) => mark.mutate({ id, is_important })} />
  </>;
}
