import { useState } from "react";
import { ExternalLink, Globe } from "lucide-react";

import { Button } from "../components/ui/button";
import { NEWS_NAV_SITES } from "../lib/newsNav";

function SiteIcon({ url, name }: { url: string; name: string }) {
  const [failed, setFailed] = useState(false);
  const domain = new URL(url).hostname;
  if (failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-neutral-900 text-sm font-semibold text-neutral-50">
        {name.slice(0, 1).toUpperCase()}
      </div>
    );
  }
  return (
    <img
      src={`https://${domain}/favicon.ico`}
      alt=""
      aria-hidden
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-md border border-neutral-200 bg-white object-contain p-1"
    />
  );
}

export function NewsPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">技术资讯</h1>
        <p className="mt-1 text-sm text-neutral-500">
          统一入口直达成熟资讯网站，内容由对应网站提供与维护。
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {NEWS_NAV_SITES.map((site) => (
          <div key={site.name} className="flex flex-col rounded-lg border border-neutral-200 bg-white p-4">
            <div className="flex items-start gap-3">
              <SiteIcon url={site.url} name={site.name} />
              <div className="min-w-0">
                <div className="text-sm font-medium">{site.name}</div>
                <div className="mt-0.5 text-xs text-neutral-500">{site.description}</div>
              </div>
            </div>
            <div className="mt-4 flex items-center justify-between">
              <span className="truncate text-xs text-neutral-400">{new URL(site.url).hostname}</span>
              <Button asChild size="sm" variant="outline">
                <a href={site.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-3.5 w-3.5" /> 打开网站
                </a>
              </Button>
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-2 text-xs text-neutral-400">
        <Globe className="h-3.5 w-3.5" />
        外部网站在新标签页打开；若某个网站无法访问，请检查网络或稍后再试。
      </div>
    </div>
  );
}
