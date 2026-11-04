/**
 * 外部技术资讯导航（PRD §2.2，2026-11 产品调整：不再自建聚合，仅统一入口）。
 *
 * 四个默认入口来自产品方案确认；站点可用性以用户实际网络为准
 * （LLM Digest 在开发网络下未连通，已如实报告，未擅自替换）。
 */

export interface NewsNavSite {
  name: string;
  url: string;
  description: string;
}

export const NEWS_NAV_SITES: NewsNavSite[] = [
  {
    name: "daily.dev",
    url: "https://daily.dev/",
    description: "软件工程、开发工具与 AI 开发的开发者资讯社区",
  },
  {
    name: "LLM Digest",
    url: "https://www.llm-digest.com/",
    description: "LLM、Agent 工程及工具链的精选摘要",
  },
  {
    name: "HotAI.news",
    url: "https://hotai.news/",
    description: "中文 AI 新闻与热点追踪",
  },
  {
    name: "Edition",
    url: "https://edition.cafe/",
    description: "Hacker News、GitHub Trending 与 RSS 聚合阅读",
  },
];
