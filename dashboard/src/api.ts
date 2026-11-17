export interface Session {
  user: { id: string; email: string; role: "owner" | "viewer" };
  company: { id: string; name: string };
  csrf_token: string;
}

export interface DocumentOut {
  id: string;
  filename: string;
  status: "pending" | "processing" | "ready" | "failed";
  error: string | null;
  chunk_count: number;
  size_bytes: number;
  created_at: string;
}

export interface FailedQuestion {
  message_id: string;
  conversation_id: string;
  question: string;
  language: string | null;
  created_at: string;
}

export interface RatingItem {
  message_id: string;
  rating: "up" | "down";
  question: string | null;
  answer: string;
  language: string | null;
  created_at: string;
}

export interface RatingsSummary {
  up: number;
  down: number;
  items: RatingItem[];
}

export interface DashboardSettings {
  company_name: string;
  site_key: string;
  allowed_domains: string[];
  store_conversations: boolean;
  handoff_email: string | null;
  telegram_chat_id: string | null;
  smtp_configured: boolean;
  telegram_configured: boolean;
}

export interface HandoffItem {
  id: string;
  email: string;
  message: string;
  language: string | null;
  email_status: "sent" | "failed" | "skipped";
  telegram_status: "sent" | "failed" | "skipped";
  error: string | null;
  created_at: string;
}

export interface UserOut {
  id: string;
  email: string;
  role: string;
  created_at: string;
}

export interface EvalCaseResult {
  id: string;
  language: string;
  category: string;
  question: string;
  passed: boolean;
  checks: Record<string, boolean>;
  answer: string;
  sources: string[];
  duration_ms: number;
  refusal_kind?: "off_topic" | "not_covered" | null;
}

export interface EvalBucket {
  total: number;
  passed: number;
}

export interface EvalSummary {
  total: number;
  passed: number;
  per_language: Record<string, EvalBucket>;
  per_category: Record<string, EvalBucket>;
}

export interface EvalState {
  status: "idle" | "running" | "done" | "failed";
  started_at?: string;
  finished_at?: string;
  total?: number;
  completed?: number;
  results?: EvalCaseResult[];
  summary?: EvalSummary;
  error?: string;
  golden: {
    total: number;
    per_language: Record<string, number>;
    per_category: Record<string, number>;
    documents: string[];
  };
  documents_ready: boolean;
}

export interface CrawlSource {
  id: string;
  url: string;
  status: "pending" | "crawling" | "ready" | "failed";
  error: string | null;
  pages_crawled: number;
  last_synced_at: string | null;
  created_at: string;
  updated_at: string;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let csrf = "";
export function setCsrf(token: string): void {
  csrf = token;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  const isForm = body instanceof FormData;
  if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrf) headers["X-CSRF-Token"] = csrf;
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: isForm ? body : body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return null as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      data && typeof data.detail === "string" ? data.detail : `HTTP ${response.status}`;
    throw new ApiError(detail, response.status);
  }
  return data as T;
}

export const api = {
  me: () => request<Session>("GET", "/api/v1/auth/me"),
  login: (email: string, password: string) =>
    request<Session>("POST", "/api/v1/auth/login", { email, password }),
  logout: () => request<{ detail: string }>("POST", "/api/v1/auth/logout"),
  documents: () => request<DocumentOut[]>("GET", "/api/v1/dashboard/documents"),
  uploadDocument: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentOut>("POST", "/api/v1/dashboard/documents", form);
  },
  deleteDocument: (id: string) => request<null>("DELETE", `/api/v1/dashboard/documents/${id}`),
  reindexDocument: (id: string) =>
    request<DocumentOut>("POST", `/api/v1/dashboard/documents/${id}/reindex`),
  failedQuestions: () => request<FailedQuestion[]>("GET", "/api/v1/dashboard/failed-questions"),
  ratings: () => request<RatingsSummary>("GET", "/api/v1/dashboard/ratings"),
  settings: () => request<DashboardSettings>("GET", "/api/v1/dashboard/settings"),
  updateSettings: (
    patch: Partial<
      Pick<
        DashboardSettings,
        "allowed_domains" | "store_conversations" | "handoff_email" | "telegram_chat_id"
      >
    >
  ) => request<DashboardSettings>("PUT", "/api/v1/dashboard/settings", patch),
  handoffs: () => request<HandoffItem[]>("GET", "/api/v1/dashboard/handoffs"),
  rotateKeys: () =>
    request<{ api_key: string; site_key: string }>("POST", "/api/v1/dashboard/keys/rotate"),
  deleteConversations: () =>
    request<{ deleted: number }>("DELETE", "/api/v1/dashboard/conversations"),
  users: () => request<UserOut[]>("GET", "/api/v1/dashboard/users"),
  addViewer: (email: string, password: string) =>
    request<UserOut>("POST", "/api/v1/dashboard/users", { email, password }),
  evalState: () => request<EvalState>("GET", "/api/v1/dashboard/eval"),
  runEval: () => request<{ status: string }>("POST", "/api/v1/dashboard/eval/run"),
  crawlSources: () => request<CrawlSource[]>("GET", "/api/v1/dashboard/crawl-sources"),
  addCrawlSource: (url: string) =>
    request<CrawlSource>("POST", "/api/v1/dashboard/crawl-sources", { url }),
  syncCrawlSource: (id: string) =>
    request<CrawlSource>("POST", `/api/v1/dashboard/crawl-sources/${id}/sync`),
  deleteCrawlSource: (id: string) =>
    request<null>("DELETE", `/api/v1/dashboard/crawl-sources/${id}`),
};