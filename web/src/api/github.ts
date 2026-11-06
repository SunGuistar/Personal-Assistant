import { api } from "../lib/api";

export interface ContributionDay {
  date: string;
  count: number;
  level: 0 | 1 | 2 | 3 | 4;
}

export interface Contributions {
  year: number;
  total: number;
  days: ContributionDay[];
  coverage: { synced: boolean; from: string | null; to: string | null };
  counting_note: string;
}

export interface ActivityItem {
  type: "commit" | "pull_request" | "issue";
  repo: string;
  title: string;
  message?: string;
  time: string;
  url: string;
}

export interface DayDetail {
  date: string;
  items: ActivityItem[];
}

export interface GithubStatus {
  configured: boolean;
  repos: number;
  commits: number;
  pull_requests: number;
  issues: number;
  last_sync: { status: string; error: string | null; updated_at: string } | null;
}

export function getGithubStatus(): Promise<GithubStatus> {
  return api("/github/status");
}

export function startGithubSync(): Promise<{ task_id: number; status: string }> {
  return api("/github/sync", { method: "POST", json: {} });
}

export function getContributions(year: number): Promise<Contributions> {
  return api(`/github/contributions?year=${year}`);
}

export function getContributionDetail(date: string): Promise<DayDetail> {
  return api(`/github/contributions/${date}`);
}
