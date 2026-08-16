/**
 * API 客户端 — 统一封装所有后端 HTTP 请求
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('ai_infra_token');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: { ...headers, ...(options?.headers as Record<string, string>) },
    ...options,
  });

  // 401 时自动跳转登录
  if (resp.status === 401) {
    const stored = localStorage.getItem('ai_infra_admin');
    localStorage.removeItem('ai_infra_token');
    localStorage.removeItem('ai_infra_admin');
    // 组织级账号回跳 /{slug}/login，平台级账号回跳 /login
    let slug: string | null = null;
    try { slug = stored ? JSON.parse(stored)?.organization_slug ?? null : null; } catch { slug = null; }
    window.location.href = slug ? `/${slug}/login` : '/login';
    throw new ApiError(401, 'Session expired');
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || resp.statusText, body);
  }
  // 204 No Content — 无响应体，不能调用 resp.json()
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

// ── 类型定义 ───────────────────────────────────────────────────────────

export interface Organization {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  rate_limit_rpm: number | null;
  rate_limit_tpm: number | null;
  budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface Department {
  id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  rate_limit_rpm: number | null;
  rate_limit_tpm: number | null;
  budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  created_at: string;
  updated_at: string;
}

export interface Team {
  id: string;
  department_id: string;
  organization_id: string;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown>;
  rate_limit_rpm: number | null;
  rate_limit_tpm: number | null;
  budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  created_at: string;
  updated_at: string;
}

export interface LlmProvider {
  id: string;
  organization_id: string;
  name: string;
  provider_type: string;
  scope_type: 'organization' | 'department' | 'team';
  department_id: string | null;
  team_id: string | null;
  base_url: string;
  api_key_encrypted: string;
  api_key_version: number;
  is_active: boolean;
  priority: number;
  weight: number;
  timeout_seconds: number;
  max_retries: number;
  supported_models: string[];
  health_status: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  key_name: string;
  scope_type: 'organization' | 'department' | 'team';
  organization_id: string;
  department_id: string | null;
  team_id: string | null;
  allowed_models: string[];
  rate_limit_rpm: number | null;
  rate_limit_tpm: number | null;
  budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  revoked_at: string | null;
  key_plain: string; // 可解密的完整 API Key
}

export interface ApiKeyWithSecret extends ApiKey {
  key: string; // 等同于 key_plain，向后兼容
}

export interface DlpRule {
  id: string;
  organization_id: string | null;
  name: string;
  description: string | null;
  rule_type: 'regex' | 'keyword' | 'ner' | 'custom';
  severity: 'low' | 'medium' | 'high' | 'critical';
  action: 'block' | 'redact' | 'warn' | 'log';
  direction: 'request' | 'response' | 'both';
  pattern: string;
  scope_type: 'organization' | 'department' | 'team';
  scope_id: string | null;
  is_active: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
}

/** 规则库条目（代码内置、只读），供「添加规则」下拉选择 */
export interface DlpRuleLibraryEntry {
  name: string;
  rule_type: 'regex' | 'keyword' | 'ner' | 'custom';
  pattern: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  action: 'block' | 'redact' | 'warn' | 'log';
  direction: 'request' | 'response' | 'both';
  description: string;
}

export interface RoutingPolicy {
  id: string;
  organization_id: string;
  name: string;
  description: string | null;
  model_pattern: string;
  strategy: string;
  provider_ids: string[];
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface AuditLogEntry {
  id: number;
  request_id: string;
  api_key_id: string | null;
  organization_id: string;
  department_id: string | null;
  team_id: string | null;
  provider_id: string | null;
  event_type: string;
  direction: string | null;
  model_requested: string | null;
  model_served: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  dlp_violations: unknown[];
  status_code: number | null;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface AuditLogResponse {
  total: number;
  offset: number;
  limit: number;
  data: AuditLogEntry[];
}

// ── Public Config ──────────────────────────────────────────────────────

export interface PublicConfig {
  proxy_base_url: string | null;
}

export const config = {
  get: () => request<PublicConfig>('/api/v1/config'),
};

// ── Auth (public) ──────────────────────────────────────────────────────

export interface OrgInfo {
  name: string;
  slug: string;
}

export const auth = {
  /** 公开：按 slug 查询组织名，供组织门户登录页展示。 */
  orgInfo: (slug: string) => request<OrgInfo>(`/api/v1/auth/org-info/${encodeURIComponent(slug)}`),
};

// ── Organizations ──────────────────────────────────────────────────────

export const organizations = {
  list: () => request<Organization[]>('/api/v1/organizations'),
  get: (id: string) => request<Organization>(`/api/v1/organizations/${id}`),
  getDefault: () => request<Organization>('/api/v1/organizations/default'),
  create: (data: Partial<Organization>) =>
    request<Organization>('/api/v1/organizations', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Organization>) =>
    request<Organization>(`/api/v1/organizations/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  /** 上传/更新组织联系二维码图片（管理员鉴权）。无返回体（204）。 */
  uploadContactImage: (orgId: string, file: File) =>
    new Promise<void>((resolve, reject) => {
      const fd = new FormData();
      fd.append('file', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${BASE_URL}/api/v1/organizations/${orgId}/contact-image`);
      const token = localStorage.getItem('ai_infra_token');
      if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      xhr.onload = () => {
        if (xhr.status === 401) {
          const stored = localStorage.getItem('ai_infra_admin');
          localStorage.removeItem('ai_infra_token');
          localStorage.removeItem('ai_infra_admin');
          let slug: string | null = null;
          try { slug = stored ? JSON.parse(stored)?.organization_slug ?? null : null; } catch { slug = null; }
          window.location.href = slug ? `/${slug}/login` : '/login';
          reject(new ApiError(401, 'Session expired'));
          return;
        }
        if (xhr.status < 200 || xhr.status >= 300) {
          let detail = xhr.statusText;
          try { detail = JSON.parse(xhr.responseText)?.detail || detail; } catch { /* keep statusText */ }
          reject(new ApiError(xhr.status, detail || `HTTP ${xhr.status}`));
          return;
        }
        resolve();
      };
      xhr.onerror = () => reject(new ApiError(0, '网络错误，上传失败'));
      xhr.send(fd);
    }),
  /** 删除组织联系二维码图片（管理员鉴权）。 */
  deleteContactImage: (orgId: string) =>
    request<void>(`/api/v1/organizations/${orgId}/contact-image`, { method: 'DELETE' }),
  /** 免登录获取组织联系方式图片的二进制 URL（登录页 ContactUs 用）。
   *  返回 null 表示未配置（404）—— 调用方据此不弹框。 */
  fetchContactImage: async (slug: string): Promise<string | null> => {
    try {
      const resp = await fetch(`${BASE_URL}/api/v1/public/orgs/${encodeURIComponent(slug)}/contact-image`);
      if (!resp.ok) return null;
      const blob = await resp.blob();
      if (!blob.size) return null;
      return URL.createObjectURL(blob);
    } catch { return null; }
  },
  setDefault: (id: string) =>
    request<Organization>(`/api/v1/organizations/${id}/default`, { method: 'POST' }),
  delete: (id: string) =>
    request<void>(`/api/v1/organizations/${id}`, { method: 'DELETE' }),
};

// ── Departments ────────────────────────────────────────────────────────

export const departments = {
  list: (orgId: string) => request<Department[]>(`/api/v1/organizations/${orgId}/departments`),
  get: (id: string) => request<Department>(`/api/v1/departments/${id}`),
  create: (orgId: string, data: Partial<Department>) =>
    request<Department>(`/api/v1/organizations/${orgId}/departments`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Department>) =>
    request<Department>(`/api/v1/departments/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<void>(`/api/v1/departments/${id}`, { method: 'DELETE' }),
};

// ── Teams ──────────────────────────────────────────────────────────────

export const teams = {
  list: (deptId: string) => request<Team[]>(`/api/v1/departments/${deptId}/teams`),
  get: (id: string) => request<Team>(`/api/v1/teams/${id}`),
  create: (deptId: string, data: Partial<Team>) =>
    request<Team>(`/api/v1/departments/${deptId}/teams`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Team>) =>
    request<Team>(`/api/v1/teams/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<void>(`/api/v1/teams/${id}`, { method: 'DELETE' }),
};

// ── Users ──────────────────────────────────────────────────────────────

export interface User {
  id: string;
  organization_id: string;
  username: string;
  display_name: string | null;
  role: string;
  department_id: string | null;
  team_id: string | null;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
}

export interface UserCreateInput {
  username: string;
  display_name?: string | null;
  role: string;
  department_id?: string | null;
  team_id?: string | null;
  is_active?: boolean;
  password: string;
}

export const users = {
  list: (orgId: string) => request<User[]>(`/api/v1/organizations/${orgId}/users`),
  get: (id: string) => request<User>(`/api/v1/users/${id}`),
  create: (orgId: string, data: UserCreateInput) =>
    request<User>(`/api/v1/organizations/${orgId}/users`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<User>) =>
    request<User>(`/api/v1/users/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  resetPassword: (id: string, password: string) =>
    request<User>(`/api/v1/users/${id}/reset-password`, { method: 'POST', body: JSON.stringify({ password }) }),
  delete: (id: string) =>
    request<void>(`/api/v1/users/${id}`, { method: 'DELETE' }),
};

// ── LLM Providers ─────────────────────────────────────────────────────

export const providers = {
  list: (orgId: string) => request<LlmProvider[]>(`/api/v1/organizations/${orgId}/providers`),
  get: (id: string) => request<LlmProvider>(`/api/v1/providers/${id}`),
  /** 创建组织级提供商 */
  create: (orgId: string, data: Partial<LlmProvider>) =>
    request<LlmProvider>(`/api/v1/organizations/${orgId}/providers`, { method: 'POST', body: JSON.stringify(data) }),
  /** 创建部门级提供商 */
  createForDept: (deptId: string, data: Partial<LlmProvider> & { organization_id: string }) =>
    request<LlmProvider>(`/api/v1/departments/${deptId}/providers`, { method: 'POST', body: JSON.stringify(data) }),
  /** 创建团队级提供商 */
  createForTeam: (teamId: string, data: Partial<LlmProvider> & { organization_id: string }) =>
    request<LlmProvider>(`/api/v1/teams/${teamId}/providers`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<LlmProvider>) =>
    request<LlmProvider>(`/api/v1/providers/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<void>(`/api/v1/providers/${id}`, { method: 'DELETE' }),
};

// ── API Keys ───────────────────────────────────────────────────────────

export const apiKeys = {
  list: (orgId: string) => request<ApiKey[]>(`/api/v1/organizations/${orgId}/api-keys`),
  get: (id: string) => request<ApiKey>(`/api/v1/api-keys/${id}`),
  /** 创建组织级 Key */
  create: (orgId: string, data: Partial<ApiKey>) =>
    request<ApiKeyWithSecret>(`/api/v1/organizations/${orgId}/api-keys`, { method: 'POST', body: JSON.stringify(data) }),
  /** 创建部门级 Key */
  createForDept: (deptId: string, data: Partial<ApiKey> & { organization_id: string }) =>
    request<ApiKeyWithSecret>(`/api/v1/departments/${deptId}/api-keys`, { method: 'POST', body: JSON.stringify(data) }),
  /** 创建团队级 Key */
  createForTeam: (teamId: string, data: Partial<ApiKey> & { organization_id: string }) =>
    request<ApiKeyWithSecret>(`/api/v1/teams/${teamId}/api-keys`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<ApiKey>) =>
    request<ApiKey>(`/api/v1/api-keys/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  revoke: (id: string) =>
    request<ApiKey>(`/api/v1/api-keys/${id}/revoke`, { method: 'POST' }),
};

// ── DLP Rules ──────────────────────────────────────────────────────────

export const dlpRules = {
  list: (orgId: string) => request<DlpRule[]>(`/api/v1/organizations/${orgId}/dlp-rules`),
  library: () => request<DlpRuleLibraryEntry[]>(`/api/v1/dlp-rules/library`),
  get: (id: string) => request<DlpRule>(`/api/v1/dlp-rules/${id}`),
  /** 从规则库添加规则：library_name + 6 项可配置字段 */
  create: (orgId: string, data: { library_name: string } & Partial<DlpRule>) =>
    request<DlpRule>(`/api/v1/organizations/${orgId}/dlp-rules`, { method: 'POST', body: JSON.stringify(data) }),
  /** 配置规则：仅 severity/action/direction/scope/priority/is_active */
  update: (id: string, data: Partial<DlpRule>) =>
    request<DlpRule>(`/api/v1/dlp-rules/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<void>(`/api/v1/dlp-rules/${id}`, { method: 'DELETE' }),
  test: (id: string, text: string, direction: string) =>
    request<{ matched: boolean; violations: unknown[]; redacted_text: string | null }>(
      `/api/v1/dlp-rules/${id}/test`,
      { method: 'POST', body: JSON.stringify({ text, direction }) },
    ),
};

// ── Routing Policies ───────────────────────────────────────────────────

export const routingPolicies = {
  list: (orgId: string) => request<RoutingPolicy[]>(`/api/v1/organizations/${orgId}/routing-policies`),
  create: (orgId: string, data: Partial<RoutingPolicy>) =>
    request<RoutingPolicy>(`/api/v1/organizations/${orgId}/routing-policies`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<RoutingPolicy>) =>
    request<RoutingPolicy>(`/api/v1/routing-policies/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<void>(`/api/v1/routing-policies/${id}`, { method: 'DELETE' }),
};

// ── Audit Logs ─────────────────────────────────────────────────────────

export const auditLogs = {
  list: (orgId: string, params?: { event_type?: string; start_time?: string; end_time?: string; limit?: number; offset?: number }) => {
    const qs = new URLSearchParams();
    if (params?.event_type) qs.set('event_type', params.event_type);
    if (params?.start_time) qs.set('start_time', params.start_time);
    if (params?.end_time) qs.set('end_time', params.end_time);
    if (params?.limit) qs.set('limit', String(params.limit));
    if (params?.offset) qs.set('offset', String(params.offset));
    const query = qs.toString();
    return request<AuditLogResponse>(`/api/v1/organizations/${orgId}/audit-logs${query ? `?${query}` : ''}`);
  },
};

// ── Budget (token consumption) ────────────────────────────────────────

export interface BudgetProviderUsage {
  provider_id: string | null;
  provider_name: string;
  provider_type: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  request_count: number;
}

export interface BudgetKeyUsage {
  api_key_id: string | null;
  key_name: string;
  key_prefix: string | null;
  budget_cap_tokens: number | null;
  is_revoked: boolean;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  request_count: number;
  providers: BudgetProviderUsage[];
}

export interface BudgetUsageResponse {
  period_start: string;
  period_end: string;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  request_count: number;
  api_keys: BudgetKeyUsage[];
}

export const budget = {
  usage: (orgId: string, params?: { start_date?: string; end_date?: string; include_revoked?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.start_date) qs.set('start_date', params.start_date);
    if (params?.end_date) qs.set('end_date', params.end_date);
    if (params?.include_revoked) qs.set('include_revoked', 'true');
    const query = qs.toString();
    return request<BudgetUsageResponse>(`/api/v1/organizations/${orgId}/budget/usage${query ? `?${query}` : ''}`);
  },
};

// ── Agent Platform: Workspaces ────────────────────────────────────────

export interface Workspace {
  id: string; organization_id: string; name: string; slug: string;
  description: string | null; storage_backend: string; root_path: string;
  config: Record<string, unknown>; scope_type: string; scope_id: string | null;
  is_active: boolean; created_at: string; updated_at: string;
}

export interface WorkspaceFile {
  id: string; workspace_id: string; path: string; size: number;
  content_hash: string | null; content: string | null; metadata: Record<string, unknown>;
  extracted_text: string | null; parse_status: 'unparsed' | 'ready' | 'unsupported' | 'failed';
  parse_kind: string | null; parse_error: string | null;
  created_at: string; updated_at: string;
}

export interface WorkspaceFilePreview {
  id: string; path: string; parse_status: WorkspaceFile['parse_status'];
  parse_kind: string | null; parse_error: string | null; extracted_text: string | null;
}

export interface WorkspaceUploadOptions {
  signal?: AbortSignal;
  onProgress?: (percent: number) => void;
  onUploadComplete?: () => void;
}

function uploadWorkspaceFile(
  url: string, file: File, path: string, tokenKey: string, options?: WorkspaceUploadOptions,
): Promise<WorkspaceFile> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('path', path);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE_URL}${url}`);
    const token = localStorage.getItem(tokenKey);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        options?.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.upload.onload = () => options?.onUploadComplete?.();
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = xhr.statusText;
        try { detail = JSON.parse(xhr.responseText)?.detail || detail; } catch { /* keep statusText */ }
        reject(new ApiError(xhr.status, detail));
        return;
      }
      try { resolve(JSON.parse(xhr.responseText) as WorkspaceFile); }
      catch { reject(new ApiError(xhr.status, '响应解析失败')); }
    };
    xhr.onerror = () => reject(new ApiError(0, '网络错误，上传失败'));
    xhr.onabort = () => reject(new DOMException('上传已取消', 'AbortError'));
    if (options?.signal) {
      if (options.signal.aborted) {
        reject(new DOMException('上传已取消', 'AbortError'));
        return;
      }
      options.signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }
    xhr.send(fd);
  });
}

export interface WorkspaceFolder {
  id: string; workspace_id: string; path: string;
  created_at: string; updated_at: string;
}

/** 工作空间树节点：随组织架构逐级嵌套，每节点携带同名绑定工作空间。 */
export interface WorkspaceTreeNode {
  node_type: 'organization' | 'department' | 'team' | 'user';
  node_id: string;
  name: string;
  workspace: {
    id: string; name: string; slug: string;
    scope_type: string; scope_id: string | null; is_active: boolean;
  } | null;
  children: WorkspaceTreeNode[];
}

export const workspaces = {
  list: (orgId: string) => request<Workspace[]>(`/api/v1/organizations/${orgId}/workspaces`),
  tree: (orgId?: string) =>
    request<WorkspaceTreeNode[]>(`/api/v1/workspaces/tree${orgId ? `?organization_id=${orgId}` : ''}`),
  get: (id: string) => request<Workspace>(`/api/v1/workspaces/${id}`),
  create: (orgId: string, data: Partial<Workspace>) =>
    request<Workspace>(`/api/v1/organizations/${orgId}/workspaces`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Workspace>) =>
    request<Workspace>(`/api/v1/workspaces/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/workspaces/${id}`, { method: 'DELETE' }),
  listFiles: (wsId: string) => request<WorkspaceFile[]>(`/api/v1/workspaces/${wsId}/files`),
  upsertFile: (wsId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    request<WorkspaceFile>(`/api/v1/workspaces/${wsId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  uploadFile: (wsId: string, file: File, path: string) =>
    uploadWorkspaceFile(`/api/v1/workspaces/${wsId}/files/upload`, file, path, 'ai_infra_token'),
  getFile: (id: string) => request<WorkspaceFile>(`/api/v1/files/${id}`),
  getFilePreview: (id: string) => request<WorkspaceFilePreview>(`/api/v1/files/${id}/preview`),
  reparseFile: (id: string) => request<WorkspaceFile>(`/api/v1/files/${id}/reparse`, { method: 'POST' }),
  updateFile: (id: string, data: { content?: string; metadata?: Record<string, unknown> }) =>
    request<WorkspaceFile>(`/api/v1/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFile: (id: string) => request<void>(`/api/v1/files/${id}`, { method: 'DELETE' }),
  listFolders: (wsId: string) => request<WorkspaceFolder[]>(`/api/v1/workspaces/${wsId}/folders`),
  createFolder: (wsId: string, data: { path: string }) =>
    request<WorkspaceFolder>(`/api/v1/workspaces/${wsId}/folders`, { method: 'POST', body: JSON.stringify(data) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/folders/${id}`, { method: 'DELETE' }),
};

// ── Agent Platform: Agents ─────────────────────────────────────────────

export interface Agent {
  id: string; organization_id: string; scope_type: string; scope_id: string | null; created_by: string | null;
  name: string; slug: string; description: string | null;
  system_prompt: string; model_alias: string; workflow: unknown[];
  memory_config: Record<string, unknown>; judge_config: Record<string, unknown>;
  workspace_id: string | null; rag_collection_id: string | null; rag_collection_ids: string[];
  judge_template_id: string | null; skill_ids: string[];
  temperature: number | null; max_tokens: number | null;
  is_active: boolean; version: number; created_at: string; updated_at: string;
}

export interface AgentScope { scope_type: string; scope_id: string | null }

export const agents = {
  list: (orgId: string, scope?: AgentScope) => {
    const qs = scope ? `?scope_type=${scope.scope_type}${scope.scope_id ? `&scope_id=${scope.scope_id}` : ''}` : '';
    return request<Agent[]>(`/api/v1/organizations/${orgId}/agents${qs}`);
  },
  get: (id: string) => request<Agent>(`/api/v1/agents/${id}`),
  create: (orgId: string, data: Partial<Agent>) =>
    request<Agent>(`/api/v1/organizations/${orgId}/agents`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Agent>) =>
    request<Agent>(`/api/v1/agents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/agents/${id}`, { method: 'DELETE' }),
};

// ── Agent Platform: RAG知识库 ────────────────────────────────────────────────

export interface RagCollection {
  id: string; organization_id: string; name: string; slug: string; description: string | null;
  embedding_model: string; embedding_dim: number | null; chunk_size: number; chunk_overlap: number;
  metadata: Record<string, unknown>; scope_type: string; scope_id: string | null;
  created_by: string | null; created_at: string; updated_at: string;
}

export interface RagDocument {
  id: string; collection_id: string; source: string; title: string | null;
  content: string; doc_hash: string | null; metadata: Record<string, unknown>;
  folder_path: string; created_by: string | null;
  // 解析入库状态：pending/parsing/chunking/embedding/ready/failed
  status: string; progress: number; parse_error: string | null;
  created_at: string; updated_at: string;
}

/** 文档解析入库状态（上传后轮询用）。 */
export interface RagDocumentStatus {
  id: string; status: string; progress: number;
  parse_error: string | null; chunk_count: number;
}

export interface RagFolder {
  id: string; collection_id: string; path: string; created_by: string | null;
  created_at: string; updated_at: string;
}

/** 终端知识库左栏树节点：用户可见的作用域单链（组织→部门→团队→个人）。 */
export interface KbNode {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id: string | null;
  name: string;
}

export interface RagChunk {
  id: string; document_id: string | null; content: string;
  chunk_index: number; has_embedding: boolean;
}

export interface RagIngestConfig {
  embedding_model: string; embedding_dim: number | null;
  chunk_size: number; chunk_overlap: number; top_k: number;
}

export interface RagScope {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id?: string | null;
}

export interface RagChunkHit {
  chunk_id: string; document_id: string | null; content: string;
  score: number; metadata: Record<string, unknown>;
}

export const rag = {
  listCollections: (orgId: string, scope?: RagScope) => {
    const qs = new URLSearchParams();
    if (scope) {
      qs.set('scope_type', scope.scope_type);
      if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    }
    const q = qs.toString();
    return request<RagCollection[]>(`/api/v1/organizations/${orgId}/rag${q ? `?${q}` : ''}`);
  },
  getCollection: (id: string) => request<RagCollection>(`/api/v1/rag/${id}`),
  createCollection: (orgId: string, data: Partial<RagCollection>) =>
    request<RagCollection>(`/api/v1/organizations/${orgId}/rag`, { method: 'POST', body: JSON.stringify(data) }),
  updateCollection: (id: string, data: Partial<RagCollection>) =>
    request<RagCollection>(`/api/v1/rag/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteCollection: (id: string) => request<void>(`/api/v1/rag/${id}`, { method: 'DELETE' }),
  listDocuments: (collId: string, folderPath?: string) => {
    const q = folderPath !== undefined ? `?folder_path=${encodeURIComponent(folderPath)}` : '';
    return request<RagDocument[]>(`/api/v1/rag/${collId}/documents${q}`);
  },
  ingestDocument: (collId: string, data: { source: string; title?: string; content: string; metadata?: Record<string, unknown>; folder_path?: string }) =>
    request<RagDocument>(`/api/v1/rag/${collId}/documents`, { method: 'POST', body: JSON.stringify(data) }),
  /** 上传文件入库（multipart）。上传字节进度经 onProgress 回调（0-1）；返回 pending 文档。 */
  uploadDocumentFile: (
    collId: string,
    file: File,
    opts: { title?: string; folder_path?: string },
    onProgress?: (ratio: number) => void,
  ) => new Promise<RagDocument>((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file);
    if (opts.title) fd.append('title', opts.title);
    if (opts.folder_path !== undefined) fd.append('folder_path', opts.folder_path);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE_URL}/api/v1/rag/${collId}/documents/upload`);
    const token = localStorage.getItem('ai_infra_token');
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    }
    xhr.onload = () => {
      if (xhr.status === 401) {
        const stored = localStorage.getItem('ai_infra_admin');
        localStorage.removeItem('ai_infra_token');
        localStorage.removeItem('ai_infra_admin');
        let slug: string | null = null;
        try { slug = stored ? JSON.parse(stored)?.organization_slug ?? null : null; } catch { slug = null; }
        window.location.href = slug ? `/${slug}/login` : '/login';
        reject(new ApiError(401, 'Session expired'));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = xhr.statusText;
        try { detail = JSON.parse(xhr.responseText)?.detail || detail; } catch { /* keep statusText */ }
        reject(new ApiError(xhr.status, detail));
        return;
      }
      try { resolve(JSON.parse(xhr.responseText) as RagDocument); }
      catch (e) { reject(new ApiError(xhr.status, '响应解析失败')); }
    };
    xhr.onerror = () => reject(new ApiError(0, '网络错误，上传失败'));
    xhr.send(fd);
  }),
  getDocumentStatus: (docId: string) =>
    request<RagDocumentStatus>(`/api/v1/rag/documents/${docId}/status`),
  updateDocument: (id: string, data: { source?: string; title?: string | null; folder_path?: string }) =>
    request<RagDocument>(`/api/v1/rag/documents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteDocument: (id: string) => request<void>(`/api/v1/rag/documents/${id}`, { method: 'DELETE' }),
  listChunks: (docId: string) => request<RagChunk[]>(`/api/v1/rag/documents/${docId}/chunks`),
  reingestDocument: (docId: string, data: { chunks: string[] | null; source?: string; title?: string | null }) =>
    request<RagDocument>(`/api/v1/rag/documents/${docId}/reingest`, { method: 'POST', body: JSON.stringify(data) }),
  listFolders: (collId: string, parent?: string) => {
    const q = parent !== undefined ? `?parent=${encodeURIComponent(parent)}` : '';
    return request<RagFolder[]>(`/api/v1/rag/${collId}/folders${q}`);
  },
  createFolder: (collId: string, path: string) =>
    request<RagFolder>(`/api/v1/rag/${collId}/folders`, { method: 'POST', body: JSON.stringify({ path }) }),
  renameFolder: (id: string, path: string) =>
    request<RagFolder>(`/api/v1/rag/folders/${id}`, { method: 'PATCH', body: JSON.stringify({ path }) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/rag/folders/${id}`, { method: 'DELETE' }),
  getIngestConfig: (orgId: string) => request<RagIngestConfig>(`/api/v1/organizations/${orgId}/rag/ingest-config`),
  setIngestConfig: (orgId: string, data: RagIngestConfig) =>
    request<RagIngestConfig>(`/api/v1/organizations/${orgId}/rag/ingest-config`, { method: 'PUT', body: JSON.stringify(data) }),
  retrieve: (collId: string, query: string, topK = 5) =>
    request<{ query: string; hits: RagChunkHit[] }>(`/api/v1/rag/${collId}/retrieve`, {
      method: 'POST', body: JSON.stringify({ query, top_k: topK }),
    }),
};

// ── Agent Platform: Judge Templates ────────────────────────────────────

export interface JudgeTemplate {
  id: string; organization_id: string; name: string; slug: string; description: string | null;
  criteria: unknown[]; scoring_rubric: string | null; is_active: boolean;
  created_at: string; updated_at: string;
}

export const judges = {
  list: (orgId: string) => request<JudgeTemplate[]>(`/api/v1/organizations/${orgId}/judges`),
  get: (id: string) => request<JudgeTemplate>(`/api/v1/judges/${id}`),
  create: (orgId: string, data: Partial<JudgeTemplate>) =>
    request<JudgeTemplate>(`/api/v1/organizations/${orgId}/judges`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<JudgeTemplate>) =>
    request<JudgeTemplate>(`/api/v1/judges/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/judges/${id}`, { method: 'DELETE' }),
};

// ── Tool Connector: Connectors ────────────────────────────────────────

export interface ToolConnector {
  id: string; organization_id: string; name: string; slug: string; description: string | null;
  type: string; base_url: string; auth_type: string; spec: Record<string, unknown>;
  is_active: boolean; health_status: string; created_at: string; updated_at: string;
}

export interface ToolEndpoint {
  id: string; connector_id: string; name: string; method: string; path: string;
  description: string | null; params_schema: Record<string, unknown>;
  response_schema: Record<string, unknown>; is_active: boolean;
  created_at: string; updated_at: string;
}

export interface ToolTestResult {
  status_code: number | null; latency_ms: number; body: unknown; error: string | null;
}

export const connectors = {
  list: (orgId: string) => request<ToolConnector[]>(`/api/v1/organizations/${orgId}/connectors`),
  get: (id: string) => request<ToolConnector>(`/api/v1/connectors/${id}`),
  create: (orgId: string, data: Partial<ToolConnector> & { auth_config?: Record<string, unknown> }) =>
    request<ToolConnector>(`/api/v1/organizations/${orgId}/connectors`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<ToolConnector> & { auth_config?: Record<string, unknown> }) =>
    request<ToolConnector>(`/api/v1/connectors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/connectors/${id}`, { method: 'DELETE' }),
  importSpec: (id: string) => request<ToolEndpoint[]>(`/api/v1/connectors/${id}/import-spec`, { method: 'POST' }),
  listEndpoints: (id: string) => request<ToolEndpoint[]>(`/api/v1/connectors/${id}/endpoints`),
  createEndpoint: (connId: string, data: Partial<ToolEndpoint>) =>
    request<ToolEndpoint>(`/api/v1/connectors/${connId}/endpoints`, { method: 'POST', body: JSON.stringify(data) }),
  updateEndpoint: (id: string, data: Partial<ToolEndpoint>) =>
    request<ToolEndpoint>(`/api/v1/endpoints/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteEndpoint: (id: string) => request<void>(`/api/v1/endpoints/${id}`, { method: 'DELETE' }),
  testEndpoint: (id: string, params: Record<string, unknown>) =>
    request<ToolTestResult>(`/api/v1/endpoints/${id}/test`, { method: 'POST', body: JSON.stringify({ params }) }),
};

// ── Tool Connector: Skills ─────────────────────────────────────────────

export interface Skill {
  id: string; organization_id: string; name: string; slug: string; description: string | null;
  definition: Record<string, unknown>; bound_endpoint_ids: string[];
  param_mapping: Record<string, unknown>; is_active: boolean;
  created_at: string; updated_at: string;
}

export const skills = {
  list: (orgId: string) => request<Skill[]>(`/api/v1/organizations/${orgId}/skills`),
  get: (id: string) => request<Skill>(`/api/v1/skills/${id}`),
  create: (orgId: string, data: Partial<Skill>) =>
    request<Skill>(`/api/v1/organizations/${orgId}/skills`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Skill>) =>
    request<Skill>(`/api/v1/skills/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/skills/${id}`, { method: 'DELETE' }),
  test: (id: string, params: Record<string, unknown>) =>
    request<ToolTestResult>(`/api/v1/skills/${id}/test`, { method: 'POST', body: JSON.stringify({ params }) }),
};

// ── Tool Connector: Skill Store（文件夹化，节点作用域）─────────────────

export interface SkillFolder {
  id: string; organization_id: string; scope_type: string; scope_id: string | null;
  name: string; slug: string; created_by: string | null;
  created_at: string; updated_at: string;
}

export interface SkillFileMeta {
  id: string; skill_folder_id: string; path: string; size: number;
  content_hash: string | null; metadata: Record<string, unknown>;
  created_at: string; updated_at: string;
}

export interface SkillFile extends SkillFileMeta {
  content: string | null;
}

/** /terminal/resources 返回的技能文件夹轻量摘要。 */
export interface SkillFolderSummary {
  id: string; name: string; slug: string;
}

/** /terminal/workspace-files 返回的工作空间文件轻量摘要（跨全部可访问工作空间，供 @ 引用下拉）。 */
export interface WorkspaceFileSummary {
  id: string; workspace_id: string; workspace_name: string;
  path: string; scope_type: string; is_binary: boolean;
}

export const skillStore = {
  listFolders: (orgId: string, scope: ScopeRef) =>
    request<SkillFolder[]>(`/api/v1/organizations/${orgId}/skill-folders?scope_type=${scope.scope_type}&scope_id=${scope.scope_id ?? ''}`),
  createFolder: (orgId: string, data: { name: string; slug: string; scope_type: string; scope_id: string | null }) =>
    request<SkillFolder>(`/api/v1/organizations/${orgId}/skill-folders`, { method: 'POST', body: JSON.stringify(data) }),
  updateFolder: (id: string, data: { name?: string; slug?: string }) =>
    request<SkillFolder>(`/api/v1/skill-folders/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/skill-folders/${id}`, { method: 'DELETE' }),
  listFiles: (folderId: string) =>
    request<SkillFileMeta[]>(`/api/v1/skill-folders/${folderId}/files`),
  upsertFile: (folderId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    request<SkillFile>(`/api/v1/skill-folders/${folderId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  getFile: (id: string) => request<SkillFile>(`/api/v1/skill-files/${id}`),
  updateFile: (id: string, data: { path?: string; content?: string; metadata?: Record<string, unknown> }) =>
    request<SkillFile>(`/api/v1/skill-files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFile: (id: string) => request<void>(`/api/v1/skill-files/${id}`, { method: 'DELETE' }),
};

// ── Tool Connector: Ontology ───────────────────────────────────────────

export interface Ontology {
  id: string; organization_id: string; name: string; slug: string; description: string | null;
  entities: unknown[]; relations: unknown[]; version: number; is_active: boolean;
  created_at: string; updated_at: string;
}

export const ontologies = {
  list: (orgId: string) => request<Ontology[]>(`/api/v1/organizations/${orgId}/ontologies`),
  get: (id: string) => request<Ontology>(`/api/v1/ontologies/${id}`),
  create: (orgId: string, data: Partial<Ontology>) =>
    request<Ontology>(`/api/v1/organizations/${orgId}/ontologies`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Ontology>) =>
    request<Ontology>(`/api/v1/ontologies/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/ontologies/${id}`, { method: 'DELETE' }),
  validate: (id: string) =>
    request<{ ok: boolean; errors: string[] }>(`/api/v1/ontologies/${id}/validate`, { method: 'POST' }),
};

// ── Tool Connector: Ontology Store（Markdown 文件 + 文件夹，节点作用域）──

export interface OntologyFolder {
  id: string; organization_id: string; scope_type: string; scope_id: string | null;
  path: string; created_by: string | null; created_at: string; updated_at: string;
}

export interface OntologyFile {
  id: string; organization_id: string; scope_type: string; scope_id: string | null;
  path: string; size: number; content_hash: string | null; content: string | null;
  metadata: Record<string, unknown>; created_by: string | null; created_at: string; updated_at: string;
}

/** /terminal/resources 返回的本体文件轻量摘要。 */
export interface OntologyFileSummary {
  id: string; name: string; path: string;
}

export const ontologyStore = {
  listFolders: (orgId: string, scope: ScopeRef) =>
    request<OntologyFolder[]>(`/api/v1/organizations/${orgId}/ontology-folders?scope_type=${scope.scope_type}&scope_id=${scope.scope_id ?? ''}`),
  createFolder: (orgId: string, data: { path: string; scope_type: string; scope_id: string | null }) =>
    request<OntologyFolder>(`/api/v1/organizations/${orgId}/ontology-folders`, { method: 'POST', body: JSON.stringify(data) }),
  renameFolder: (id: string, path: string) =>
    request<OntologyFolder>(`/api/v1/ontology-folders/${id}`, { method: 'PATCH', body: JSON.stringify({ path }) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/ontology-folders/${id}`, { method: 'DELETE' }),
  listFiles: (orgId: string, scope: ScopeRef) =>
    request<OntologyFile[]>(`/api/v1/organizations/${orgId}/ontology-files?scope_type=${scope.scope_type}&scope_id=${scope.scope_id ?? ''}`),
  upsertFile: (orgId: string, data: { path: string; content: string; metadata?: Record<string, unknown>; scope_type: string; scope_id: string | null }) =>
    request<OntologyFile>(`/api/v1/organizations/${orgId}/ontology-files`, { method: 'POST', body: JSON.stringify(data) }),
  getFile: (id: string) => request<OntologyFile>(`/api/v1/ontology-files/${id}`),
  updateFile: (id: string, data: { path?: string; content?: string; metadata?: Record<string, unknown> }) =>
    request<OntologyFile>(`/api/v1/ontology-files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFile: (id: string) => request<void>(`/api/v1/ontology-files/${id}`, { method: 'DELETE' }),
};

// ── Tool Connector: Data Interfaces (独立数据结构) ──────────────────────

export interface DataSystem {
  id: string; organization_id: string; scope_type: string; scope_id: string | null;
  name: string; description: string | null; is_active: boolean;
  created_at: string; updated_at: string;
}

export interface DataInterface {
  id: string; data_system_id: string; name: string; method: string | null; path: string | null;
  description: string | null; params_schema: Record<string, unknown>;
  response_schema: Record<string, unknown>; is_active: boolean;
  created_at: string; updated_at: string;
}

export interface ScopeRef { scope_type: string; scope_id: string | null }

export const dataInterfaces = {
  listSystems: (orgId: string, scope: ScopeRef) =>
    request<DataSystem[]>(`/api/v1/organizations/${orgId}/data-systems?scope_type=${scope.scope_type}&scope_id=${scope.scope_id ?? ''}`),
  getSystem: (id: string) => request<DataSystem>(`/api/v1/data-systems/${id}`),
  updateSystem: (id: string, data: Partial<DataSystem>) =>
    request<DataSystem>(`/api/v1/data-systems/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  listInterfaces: (systemId: string) =>
    request<DataInterface[]>(`/api/v1/data-systems/${systemId}/data-interfaces`),
  getInterface: (id: string) => request<DataInterface>(`/api/v1/data-interfaces/${id}`),
  updateInterface: (id: string, data: Partial<DataInterface>) =>
    request<DataInterface>(`/api/v1/data-interfaces/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
};

// ── App Monitor ────────────────────────────────────────────────────────

export interface RouterMetrics {
  requests: number; input_tokens: number; output_tokens: number;
  error_count: number; error_rate: number; avg_latency_ms: number;
  dlp_violation_count: number;
  by_provider: { provider_id: string | null; provider_name: string; requests: number; input_tokens: number; output_tokens: number }[];
}

export interface AgentMetrics {
  runs: number; success_count: number; success_rate: number;
  input_tokens: number; output_tokens: number; avg_latency_ms: number;
  by_agent: {
    agent_id: string | null; exec_mode: string; type: 'agent' | 'general';
    agent_name: string; runs: number; input_tokens: number; output_tokens: number;
  }[];
  components?: {
    workspace: { runs: number; ops: number };
    rag: { runs: number; hits: number };
    memory: { load_runs: number; facts_loaded: number; extract_runs: number; facts_saved: number };
  };
}

export interface ToolMetrics {
  calls: number; success_count: number; error_count: number; error_rate: number; avg_latency_ms: number;
  by_connector: {
    connector_id: string | null; connector_name: string; type: string | null; is_active: boolean | null;
    health_status: string; calls: number; error_count: number; error_rate: number; avg_latency_ms: number;
    last_called_at: string | null;
  }[];
  by_skill: {
    skill_id: string; skill_name: string; scope_type: string | null; scope_id: string | null;
    calls: number; error_count: number; error_rate: number; avg_latency_ms: number;
  }[];
  by_endpoint: {
    endpoint_id: string; endpoint_name: string; connector_name: string; method: string | null; path: string | null;
    calls: number; error_count: number; error_rate: number; avg_latency_ms: number;
  }[];
  inventory: {
    connectors: { total: number; active: number; inactive: number; by_health: Record<string, number> };
    data_interfaces: { systems_total: number; interfaces_total: number; active: number; inactive: number };
    skills: { folders_total: number; files_total: number };
    ontology: { folders_total: number; files_total: number };
  };
}

export interface OverviewMetrics { router: RouterMetrics; agent: AgentMetrics; tool: ToolMetrics; }

export const monitor = {
  overview: (orgId: string) => request<OverviewMetrics>(`/api/v1/organizations/${orgId}/monitor/overview`),
  router: (orgId: string) => request<RouterMetrics>(`/api/v1/organizations/${orgId}/monitor/router`),
  agents: (orgId: string) => request<AgentMetrics>(`/api/v1/organizations/${orgId}/monitor/agents`),
  tools: (orgId: string) => request<ToolMetrics>(`/api/v1/organizations/${orgId}/monitor/tools`),
};

// ── Terminal User Portal (user JWT) ────────────────────────────────────
// 终端用户端使用独立 localStorage 键 ai_infra_user_token，与管理员 token 隔离。

const USER_TOKEN_KEY = 'ai_infra_user_token';

function userRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem(USER_TOKEN_KEY);
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(`${BASE_URL}${path}`, { headers: { ...headers, ...(options?.headers as Record<string, string>) }, ...options })
    .then(async (resp) => {
      if (resp.status === 401) {
        localStorage.removeItem(USER_TOKEN_KEY);
        localStorage.removeItem('ai_infra_user');
        // 回跳到当前 slug 的用户登录页（或平台 /login 兜底）
        const m = window.location.pathname.match(/^\/([^/]+)\/terminal/);
        const slug = m ? m[1] : null;
        window.location.href = slug ? `/${slug}/terminal/login` : '/login';
        throw new ApiError(401, 'Session expired');
      }
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new ApiError(resp.status, body.detail || resp.statusText, body);
      }
      if (resp.status === 204) return undefined as T;
      return resp.json();
    });
}

export interface TerminalUser {
  user: User;
  department_id: string | null;
  team_id: string | null;
  scopes: [string, string | null][];
}

export interface TerminalResources {
  workspaces: Workspace[];
  skills: SkillFolderSummary[];
  ontologies: OntologyFileSummary[];
  rags: RagCollection[];
  /** 用户默认装配：默认工作空间（个人）+ 默认模型（最近一次使用）。 */
  defaults?: { workspace_id: string | null; model_alias: string | null };
}

export interface TerminalModels {
  /** 用户可用的原始模型名（按可访问 API Key 聚合，embedding 已过滤）。 */
  models: string[];
}

export interface TaskConfig {
  workspace_id: string | null;
  // 技能 / 本体 / RAG 知识库不在任务配置中指定：技能在输入框用 /slug 引用（运行时主动执行），
  // 本体与知识库运行时按用户权限自动注入/检索。
  model_alias: string | null;
  /** 执行模式：craft（自主多步执行）/ ask（只读单轮问答）/ plan（出方案不执行） */
  exec_mode: 'craft' | 'ask' | 'plan';
  /** 终端「选智能体」逐次运行覆盖（不落库）：UUID=该次用此智能体；null=通用智能体（不绑模板）。
   *  注意：此字段仅前端态，不写入 task.config；run 请求里随消息一起发送，由后端 exclude_unset 判定覆盖。 */
  template_agent_id?: string | null;
}

export interface TerminalAgent {
  id: string; name: string; slug: string;
  scope_type: string; scope_id: string | null;
  model_alias: string; description: string | null;
}

export interface TerminalTask {
  id: string;
  organization_id: string;
  user_id: string;
  department_id: string | null;
  team_id: string | null;
  session_id: string;
  title: string;
  message: string;
  config: TaskConfig;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TerminalTaskMessage {
  id: string;
  task_id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TerminalTaskWithMessages extends TerminalTask {
  messages: TerminalTaskMessage[];
  /** 该任务最新一次 run 的状态（agent_runs.status）：running/success/error。
   *  前端据此判断是否调 GET /stream 重连续接（后台 detach 执行，刷新不丢）。 */
  run_status?: string | null;
}

export interface TerminalMemoryItem {
  id: string;
  scope_type: string;
  scope_id: string | null;
  category: string;
  content: string;
  source: string;
  created_at: string | null;
}

export const terminal = {
  // 登录端点的 401 是「凭据错误」（预期业务错误），不是「会话过期」：
  // 不能复用 request 的 401 自动跳转（那会因无 ai_infra_admin 而 fallback 到 /login 平台登录页）。
  // 这里走裸 fetch，401 当普通错误抛出，由登录页 message.error 提示并留在原 slug 终端登录页。
  loginBySlug: async (slug: string, username: string, password: string) => {
    const resp = await fetch(`${BASE_URL}/api/v1/users/login-by-slug`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug, username, password }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new ApiError(resp.status, body.detail || resp.statusText, body);
    }
    return resp.json() as Promise<{ access_token: string; must_change_password: boolean; user: User }>;
  },
  me: () => userRequest<TerminalUser>('/api/v1/terminal/me'),
  resources: () => userRequest<TerminalResources>('/api/v1/terminal/resources'),
  models: () => userRequest<TerminalModels>('/api/v1/terminal/models'),
  agents: () => userRequest<{ agents: TerminalAgent[] }>('/api/v1/terminal/agents'),
  // ── 终端智能体管理（用户级）：列表展示权限范围内可见、改删仅限自己创建的 ──
  listAgents: (scope?: { scope_type: string; scope_id?: string | null }) => {
    const url = scope
      ? `/api/v1/terminal/agents?${new URLSearchParams({ scope_type: scope.scope_type, ...(scope.scope_id ? { scope_id: scope.scope_id } : {}) }).toString()}`
      : '/api/v1/terminal/agents';
    return userRequest<{ agents: Agent[] }>(url).then((r) => r.agents);
  },
  createAgent: (data: Partial<Agent>) =>
    userRequest<Agent>('/api/v1/terminal/agents', { method: 'POST', body: JSON.stringify(data) }),
  updateAgent: (id: string, data: Partial<Agent>) =>
    userRequest<Agent>(`/api/v1/terminal/agents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteAgent: (id: string) =>
    userRequest<void>(`/api/v1/terminal/agents/${id}`, { method: 'DELETE' }),
  memory: () => userRequest<TerminalMemoryItem[]>('/api/v1/terminal/memory'),
  /** 即时生成归口用户 skills 包 zip 并下载（鉴权内嵌、即时轮换；无需在第三方端再输凭证）。 */
  exportSkillsPack: async (): Promise<void> => {
    const token = localStorage.getItem(USER_TOKEN_KEY);
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const resp = await fetch(`${BASE_URL}/api/v1/terminal/skills-pack/export`, { method: 'POST', headers });
    if (resp.status === 401) {
      localStorage.removeItem(USER_TOKEN_KEY);
      localStorage.removeItem('ai_infra_user');
      const m = window.location.pathname.match(/^\/([^/]+)\/terminal/);
      const slug = m ? m[1] : null;
      window.location.href = slug ? `/${slug}/terminal/login` : '/login';
      throw new ApiError(401, 'Session expired');
    }
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new ApiError(resp.status, body.detail || resp.statusText, body);
    }
    const blob = await resp.blob();
    if (!blob.size) return;
    const disposition = resp.headers.get('content-disposition') || '';
    const m = /filename="?([^"]+)"?/.exec(disposition);
    const filename = m?.[1] || 'skills-pack.zip';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
  },
  listTasks: () => userRequest<TerminalTask[]>('/api/v1/terminal/tasks'),
  createTask: (data: { title?: string; message: string; config: TaskConfig }) =>
    userRequest<TerminalTask>('/api/v1/terminal/tasks', { method: 'POST', body: JSON.stringify(data) }),
  getTask: (id: string) => userRequest<TerminalTaskWithMessages>(`/api/v1/terminal/tasks/${id}`),
  updateTask: (id: string, data: Partial<{ title: string; status: string; config: TaskConfig }>) =>
    userRequest<TerminalTask>(`/api/v1/terminal/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTask: (id: string) => userRequest<void>(`/api/v1/terminal/tasks/${id}`, { method: 'DELETE' }),
  /** 删除一整轮对话（user+assistant 消息），并清理仅本轮产出、未被后续轮次覆盖的工作空间文件。 */
  deleteTaskMessage: (taskId: string, messageId: string) =>
    userRequest<void>(`/api/v1/terminal/tasks/${taskId}/messages/${messageId}`, { method: 'DELETE' }),
  runTask: (id: string, message: string, template_agent_id?: string | null, attachment_file_ids: string[] = []) =>
    userRequest<{ assistant: string; steps: unknown[]; usage: Record<string, number>; run_id: number; latency_ms: number }>(
      `/api/v1/terminal/tasks/${id}/run`,
      { method: 'POST', body: JSON.stringify({ message, stream: false, template_agent_id: template_agent_id ?? null, attachment_file_ids }) },
    ),
  /** 流式执行：返回原始 Response，由调用方解析 SSE（仿 AgentPlayground）。
   *  template_agent_id 逐次覆盖（不落库）：undefined=沿用 task.config；null=通用；UUID=该次用此智能体。 */
  runTaskStream: (
    id: string, message: string, signal: AbortSignal,
    template_agent_id?: string | null, attachment_file_ids: string[] = [],
  ) =>
    fetch(`${BASE_URL}/api/v1/terminal/tasks/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(USER_TOKEN_KEY) || ''}` },
      body: JSON.stringify({ message, stream: true, template_agent_id: template_agent_id ?? null, attachment_file_ids }),
      signal,
    }),
  /** resume：重连/回放一个运行中或已完成的 run（后台 detach 执行，刷新不丢）。 */
  streamTask: (id: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/v1/terminal/tasks/${id}/stream`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${localStorage.getItem(USER_TOKEN_KEY) || ''}` },
      signal,
    }),
  /** 取消运行中的 run（真停后台 asyncio.Task，非仅断读端）。 */
  cancelTask: (id: string) =>
    userRequest<{ cancelled: boolean }>(`/api/v1/terminal/tasks/${id}/cancel`, { method: 'POST' }),
  listWsFiles: (wsId: string) => userRequest<WorkspaceFile[]>(`/api/v1/terminal/workspaces/${wsId}/files`),
  /** 用户可访问的全部工作空间文件（组织/部门/团队/个人并集），供任务输入框 @ 引用下拉。 */
  listAllWsFiles: () => userRequest<WorkspaceFileSummary[]>('/api/v1/terminal/workspace-files'),
  upsertWsFile: (wsId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/workspaces/${wsId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  uploadWsFile: (wsId: string, file: File, path: string, options?: WorkspaceUploadOptions) =>
    uploadWorkspaceFile(`/api/v1/terminal/workspaces/${wsId}/files/upload`, file, path, USER_TOKEN_KEY, options),
  getWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`),
  getWsFilePreview: (id: string) => userRequest<WorkspaceFilePreview>(`/api/v1/terminal/files/${id}/preview`),
  reparseWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/reparse`, { method: 'POST' }),
  updateWsFile: (id: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteWsFile: (id: string) => userRequest<void>(`/api/v1/terminal/files/${id}`, { method: 'DELETE' }),
  listWsFolders: (wsId: string) => userRequest<WorkspaceFolder[]>(`/api/v1/terminal/workspaces/${wsId}/folders`),
  createWsFolder: (wsId: string, data: { path: string }) =>
    userRequest<WorkspaceFolder>(`/api/v1/terminal/workspaces/${wsId}/folders`, { method: 'POST', body: JSON.stringify(data) }),
  deleteWsFolder: (folderId: string) => userRequest<void>(`/api/v1/terminal/folders/${folderId}`, { method: 'DELETE' }),

  // ── 知识库（RAG）：终端用户 scope 内可见；删除/重命名/编辑仅限自己创建 ──
  kbNodes: () => userRequest<KbNode[]>('/api/v1/terminal/kb-nodes'),
  listKbCollections: (scope: { scope_type: string; scope_id?: string | null }) => {
    const qs = new URLSearchParams({ scope_type: scope.scope_type });
    if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    return userRequest<RagCollection[]>(`/api/v1/terminal/rag?${qs.toString()}`);
  },
  createKbCollection: (data: {
    name: string; description?: string | null; chunk_size: number; chunk_overlap: number;
    scope_type: string; scope_id?: string | null;
  }) => userRequest<RagCollection>('/api/v1/terminal/rag', { method: 'POST', body: JSON.stringify(data) }),
  updateKbCollection: (id: string, data: { name?: string; description?: string | null; chunk_size?: number; chunk_overlap?: number }) =>
    userRequest<RagCollection>(`/api/v1/terminal/rag/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteKbCollection: (id: string) => userRequest<void>(`/api/v1/terminal/rag/${id}`, { method: 'DELETE' }),
  listKbFolders: (collId: string, parent?: string) => {
    const q = parent !== undefined ? `?parent=${encodeURIComponent(parent)}` : '';
    return userRequest<RagFolder[]>(`/api/v1/terminal/rag/${collId}/folders${q}`);
  },
  createKbFolder: (collId: string, path: string) =>
    userRequest<RagFolder>(`/api/v1/terminal/rag/${collId}/folders`, { method: 'POST', body: JSON.stringify({ path }) }),
  renameKbFolder: (id: string, path: string) =>
    userRequest<RagFolder>(`/api/v1/terminal/rag/folders/${id}`, { method: 'PATCH', body: JSON.stringify({ path }) }),
  deleteKbFolder: (id: string) => userRequest<void>(`/api/v1/terminal/rag/folders/${id}`, { method: 'DELETE' }),
  listKbDocuments: (collId: string, folderPath?: string) => {
    const q = folderPath !== undefined ? `?folder_path=${encodeURIComponent(folderPath)}` : '';
    return userRequest<RagDocument[]>(`/api/v1/terminal/rag/${collId}/documents${q}`);
  },
  ingestKbDocument: (collId: string, data: { source: string; title?: string | null; content: string; folder_path?: string }) =>
    userRequest<RagDocument>(`/api/v1/terminal/rag/${collId}/documents`, { method: 'POST', body: JSON.stringify(data) }),
  /** 上传文件入库（multipart，与管理端一致）。上传字节进度经 onProgress 回调（0-1）；返回 pending 文档。 */
  uploadKbDocumentFile: (
    collId: string,
    file: File,
    opts: { title?: string; folder_path?: string },
    onProgress?: (ratio: number) => void,
  ) => new Promise<RagDocument>((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file);
    if (opts.title) fd.append('title', opts.title);
    if (opts.folder_path !== undefined) fd.append('folder_path', opts.folder_path);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE_URL}/api/v1/terminal/rag/${collId}/documents/upload`);
    const token = localStorage.getItem(USER_TOKEN_KEY);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    if (onProgress && xhr.upload) {
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    }
    xhr.onload = () => {
      if (xhr.status === 401) {
        localStorage.removeItem(USER_TOKEN_KEY);
        localStorage.removeItem('ai_infra_user');
        const m = window.location.pathname.match(/^\/([^/]+)\/terminal/);
        const slug = m ? m[1] : null;
        window.location.href = slug ? `/${slug}/terminal/login` : '/login';
        reject(new ApiError(401, 'Session expired'));
        return;
      }
      if (xhr.status < 200 || xhr.status >= 300) {
        let detail = xhr.statusText;
        try { detail = JSON.parse(xhr.responseText)?.detail || detail; } catch { /* keep statusText */ }
        reject(new ApiError(xhr.status, detail));
        return;
      }
      try { resolve(JSON.parse(xhr.responseText) as RagDocument); }
      catch { reject(new ApiError(xhr.status, '响应解析失败')); }
    };
    xhr.onerror = () => reject(new ApiError(0, '网络错误，上传失败'));
    xhr.send(fd);
  }),
  getKbDocStatus: (docId: string) =>
    userRequest<RagDocumentStatus>(`/api/v1/terminal/rag/documents/${docId}/status`),
  updateKbDocument: (id: string, data: { source?: string; title?: string | null }) =>
    userRequest<RagDocument>(`/api/v1/terminal/rag/documents/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteKbDocument: (id: string) => userRequest<void>(`/api/v1/terminal/rag/documents/${id}`, { method: 'DELETE' }),
  listDocChunks: (docId: string) => userRequest<RagChunk[]>(`/api/v1/terminal/rag/documents/${docId}/chunks`),
  reingestDoc: (docId: string, data: { chunks: string[] | null; source?: string; title?: string | null }) =>
    userRequest<RagDocument>(`/api/v1/terminal/rag/documents/${docId}/reingest`, { method: 'POST', body: JSON.stringify(data) }),

  // ── 数据接口：终端用户 scope 内可见，只读 + 查看输入输出样例 ──
  listDataSystems: (scope: { scope_type: string; scope_id?: string | null }) => {
    const qs = new URLSearchParams({ scope_type: scope.scope_type });
    if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    return userRequest<DataSystem[]>(`/api/v1/terminal/data-systems?${qs.toString()}`);
  },
  listDataInterfaces: (systemId: string) =>
    userRequest<DataInterface[]>(`/api/v1/terminal/data-systems/${systemId}/data-interfaces`),

  // ── 本体（Markdown 文件 + 文件夹）：终端用户 scope 内可见；删除/重命名/编辑仅限自己创建 ──
  /** 左栏 scope 单链（与 kb-nodes 同源，资源无关）。 */
  ontologyNodes: () => userRequest<KbNode[]>('/api/v1/terminal/kb-nodes'),
  listOntologyFolders: (scope: { scope_type: string; scope_id?: string | null }) => {
    const qs = new URLSearchParams({ scope_type: scope.scope_type });
    if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    return userRequest<OntologyFolder[]>(`/api/v1/terminal/ontology-folders?${qs.toString()}`);
  },
  createOntologyFolder: (data: { path: string; scope_type: string; scope_id: string | null }) =>
    userRequest<OntologyFolder>('/api/v1/terminal/ontology-folders', { method: 'POST', body: JSON.stringify(data) }),
  renameOntologyFolder: (id: string, path: string) =>
    userRequest<OntologyFolder>(`/api/v1/terminal/ontology-folders/${id}`, { method: 'PATCH', body: JSON.stringify({ path }) }),
  deleteOntologyFolder: (id: string) => userRequest<void>(`/api/v1/terminal/ontology-folders/${id}`, { method: 'DELETE' }),
  listOntologyFiles: (scope: { scope_type: string; scope_id?: string | null }) => {
    const qs = new URLSearchParams({ scope_type: scope.scope_type });
    if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    return userRequest<OntologyFile[]>(`/api/v1/terminal/ontology-files?${qs.toString()}`);
  },
  upsertOntologyFile: (data: { path: string; content: string; metadata?: Record<string, unknown>; scope_type: string; scope_id: string | null }) =>
    userRequest<OntologyFile>('/api/v1/terminal/ontology-files', { method: 'POST', body: JSON.stringify(data) }),
  getOntologyFile: (id: string) => userRequest<OntologyFile>(`/api/v1/terminal/ontology-files/${id}`),
  updateOntologyFile: (id: string, data: { path?: string; content?: string; metadata?: Record<string, unknown> }) =>
    userRequest<OntologyFile>(`/api/v1/terminal/ontology-files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteOntologyFile: (id: string) => userRequest<void>(`/api/v1/terminal/ontology-files/${id}`, { method: 'DELETE' }),

  // ── 技能（SkillFolder + SkillFile）：终端用户 scope 内可见；删除/重命名/补传仅限自己创建 ──
  /** 左栏 scope 单链（与 kb-nodes 同源，资源无关）。 */
  skillNodes: () => userRequest<KbNode[]>('/api/v1/terminal/kb-nodes'),
  listSkills: (scope: { scope_type: string; scope_id?: string | null }) => {
    const qs = new URLSearchParams({ scope_type: scope.scope_type });
    if (scope.scope_id) qs.set('scope_id', scope.scope_id);
    return userRequest<SkillFolder[]>(`/api/v1/terminal/skills?${qs.toString()}`);
  },
  createSkill: (data: { name: string; slug: string; scope_type: string; scope_id: string | null }) =>
    userRequest<SkillFolder>('/api/v1/terminal/skills', { method: 'POST', body: JSON.stringify(data) }),
  updateSkill: (id: string, data: { name?: string }) =>
    userRequest<SkillFolder>(`/api/v1/terminal/skills/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteSkill: (id: string) => userRequest<void>(`/api/v1/terminal/skills/${id}`, { method: 'DELETE' }),
  listSkillFiles: (folderId: string) =>
    userRequest<SkillFileMeta[]>(`/api/v1/terminal/skills/${folderId}/files`),
  upsertSkillFile: (folderId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<SkillFile>(`/api/v1/terminal/skills/${folderId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  getSkillFile: (id: string) => userRequest<SkillFile>(`/api/v1/terminal/skill-files/${id}`),
  deleteSkillFile: (id: string) => userRequest<void>(`/api/v1/terminal/skill-files/${id}`, { method: 'DELETE' }),
};

// ── Memory (随组织架构逐级嵌套的长期记忆树) ────────────────────────────

export interface MemoryItem {
  id: string;
  organization_id: string;
  scope_type: string;
  scope_id: string | null;
  category: string;
  content: string;
  source: string;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MemoryTreeNode {
  node_type: 'organization' | 'department' | 'team' | 'user';
  node_id: string;
  name: string;
  memory: {
    id: string;
    scope_type: string;
    scope_id: string | null;
    category: string;
    content: string;
    source: string;
  } | null;
  children: MemoryTreeNode[];
}

export const memory = {
  tree: (orgId?: string) =>
    request<MemoryTreeNode[]>(`/api/v1/memory/tree${orgId ? `?organization_id=${orgId}` : ''}`),
  list: (orgId: string, params?: { scope_type?: string; scope_id?: string }) => {
    const qs = new URLSearchParams();
    if (params?.scope_type) qs.set('scope_type', params.scope_type);
    if (params?.scope_id) qs.set('scope_id', params.scope_id);
    const query = qs.toString();
    return request<MemoryItem[]>(`/api/v1/organizations/${orgId}/memory${query ? `?${query}` : ''}`);
  },
  create: (orgId: string, data: Partial<MemoryItem>) =>
    request<MemoryItem>(`/api/v1/organizations/${orgId}/memory`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<MemoryItem>) =>
    request<MemoryItem>(`/api/v1/memory/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/memory/${id}`, { method: 'DELETE' }),
};
