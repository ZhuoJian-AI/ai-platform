/**
 * API 客户端 — 统一封装所有后端 HTTP 请求
 */

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('ai_infra_token');
  const isMultipart = options?.body instanceof FormData;
  const headers: Record<string, string> = isMultipart ? {} : { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const { headers: optionHeaders, ...requestOptions } = options ?? {};

  const resp = await fetch(`${BASE_URL}${path}`, {
    ...requestOptions,
    headers: { ...headers, ...(optionHeaders as Record<string, string> | undefined) },
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

async function requestText(path: string, options?: RequestInit): Promise<string> {
  const token = localStorage.getItem('ai_infra_token');
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers: { ...headers, ...(options?.headers as Record<string, string> | undefined) } });
  if (resp.status === 401) {
    const stored = localStorage.getItem('ai_infra_admin');
    localStorage.removeItem('ai_infra_token');
    localStorage.removeItem('ai_infra_admin');
    let slug: string | null = null;
    try { slug = stored ? JSON.parse(stored)?.organization_slug ?? null : null; } catch { slug = null; }
    window.location.href = slug ? `/${slug}/login` : '/login';
    throw new ApiError(401, 'Session expired');
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || resp.statusText, body);
  }
  return resp.text();
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
  parent_id: string | null;
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
  vendor: 'openai' | 'anthropic' | 'azure_openai' | 'aliyun_bailian' | 'volcengine_ark' | 'xiaomi_mimo' | 'custom';
  provider_type: string;
  region: string | null;
  workspace_id: string | null;
  scope_type: 'organization' | 'department' | 'team';
  department_id: string | null;
  team_id: string | null;
  base_url: string;
  api_key_masked: string;
  api_key_version: number;
  is_active: boolean;
  priority: number;
  weight: number;
  timeout_seconds: number;
  max_retries: number;
  supported_models: string[];
  health_status: string;
  config: Record<string, unknown>;
  model_deployments: ModelDeployment[];
  created_at: string;
  updated_at: string;
}

export type ModelCapability =
  | 'chat'
  | 'vision'
  | 'embedding'
  | 'image_generation'
  | 'audio_understanding'
  | 'speech_to_text'
  | 'text_to_speech'
  | 'voice_design'
  | 'voice_clone';

export interface ModelDeployment {
  id: string;
  provider_id: string;
  model_id: string;
  display_name: string | null;
  adapter: string;
  capabilities: ModelCapability[];
  base_url_override: string | null;
  endpoint_path: string | null;
  embedding_dimensions: number | null;
  routing_priority: number;
  is_active: boolean;
  verification_status: 'unverified' | 'verified' | 'failed' | 'legacy';
  last_error: string | null;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ModelDeploymentInput {
  model_id: string;
  display_name?: string;
  adapter: string;
  capabilities: ModelCapability[];
  base_url_override?: string;
  endpoint_path?: string;
  embedding_dimensions?: number;
  routing_priority?: number;
  is_active?: boolean;
  config?: Record<string, unknown>;
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
  role_ids: string[];
  roles: RoleSummary[];
  permission_codes: string[];
  effective_data_scopes: {
    unrestricted: boolean;
    include_self: boolean;
    own_only: boolean;
    department_ids: string[];
  } | null;
  department_ids: string[];
  department_id: string | null;
  team_id: string | null;
  is_active: boolean;
  must_change_password: boolean;
  manager_scopes: ManagerScopeGrant[];
  created_at: string;
  updated_at: string;
}

async function requestBlob(path: string, tokenKey: string, signal?: AbortSignal): Promise<Blob> {
  const token = localStorage.getItem(tokenKey);
  const resp = await fetch(`${BASE_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body.detail || resp.statusText, body);
  }
  return resp.blob();
}

export interface ManagerScopeGrant {
  scope_type: 'department' | 'team';
  scope_id: string;
}

export interface UserCreateInput {
  username: string;
  display_name?: string | null;
  role: string;
  role_ids?: string[];
  department_ids?: string[];
  department_id?: string | null;
  team_id?: string | null;
  is_active?: boolean;
  password: string;
  manager_scopes?: ManagerScopeGrant[];
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

export type RoleDataScope = 'all' | 'custom_departments' | 'department' | 'department_and_children' | 'self';

export interface RoleSummary {
  id: string;
  name: string;
  code: string;
  data_scope: RoleDataScope;
  is_builtin: boolean;
}

export interface Role extends RoleSummary {
  organization_id: string;
  description: string | null;
  is_active: boolean;
  permission_codes: string[];
  department_ids: string[];
  created_at: string;
  updated_at: string;
}

export const roles = {
  list: (orgId: string) => request<Role[]>(`/api/v1/organizations/${orgId}/roles`),
  create: (orgId: string, data: Partial<Role>) =>
    request<Role>(`/api/v1/organizations/${orgId}/roles`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Role>) =>
    request<Role>(`/api/v1/roles/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  replacePermissions: (id: string, permissionCodes: string[]) =>
    request<Role>(`/api/v1/roles/${id}/permissions`, {
      method: 'PUT', body: JSON.stringify({ permission_codes: permissionCodes }),
    }),
  replaceDataScope: (id: string, dataScope: RoleDataScope, departmentIds: string[] = []) =>
    request<Role>(`/api/v1/roles/${id}/data-scope`, {
      method: 'PUT', body: JSON.stringify({ data_scope: dataScope, department_ids: departmentIds }),
    }),
  replaceUserRoles: (userId: string, roleIds: string[]) =>
    request<User>(`/api/v1/users/${userId}/roles`, {
      method: 'PUT', body: JSON.stringify({ role_ids: roleIds }),
    }),
  delete: (id: string) => request<void>(`/api/v1/roles/${id}`, { method: 'DELETE' }),
};

export interface VoiceProfile {
  id: string;
  organization_id: string;
  name: string;
  voice_type: 'builtin' | 'designed' | 'cloned';
  provider_voice_id: string | null;
  design_prompt: string | null;
  sample_file_id: string | null;
  status: string;
  config: Record<string, unknown>;
  grants: { id: string; scope_type: string; scope_id: string | null }[];
  created_at: string;
  updated_at: string;
}

export interface VoiceGrantInput {
  scope_type: 'organization' | 'role' | 'department' | 'user';
  scope_id?: string | null;
}

export interface MultimodalJob {
  id: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed' | 'cancelled';
  request_id: string;
  result: Record<string, unknown>;
  usage: Record<string, unknown>;
  output_url: string | null;
  error_category: string | null;
  error_detail: string | null;
}

export const multimodal = {
  voices: () => userRequest<VoiceProfile[]>('/api/v1/multimodal/voices'),
  transcribe: (workspaceFileId: string, language: 'auto' | 'zh' | 'en' = 'auto') =>
    userRequest<{ job_id: string; request_id: string; status: string }>('/api/v1/multimodal/audio/transcriptions', {
      method: 'POST', body: JSON.stringify({ workspace_file_id: workspaceFileId, language }),
    }),
  speech: (data: {
    text: string; voice_profile_id: string; style?: string; speed?: number; format?: 'wav' | 'mp3';
  }) => userRequest<{ job_id: string; request_id: string; status: string }>('/api/v1/multimodal/speech', {
    method: 'POST', body: JSON.stringify(data),
  }),
  job: (id: string) => userRequest<MultimodalJob>(`/api/v1/multimodal/jobs/${id}`),
};

export const voiceAdmin = {
  list: (organizationId: string) => request<VoiceProfile[]>(
    `/api/v1/multimodal/voice-admin?organization_id=${encodeURIComponent(organizationId)}`,
  ),
  createBuiltin: (organizationId: string, data: {
    name: string; provider_voice_id: string; grants: VoiceGrantInput[];
  }) => request<VoiceProfile>(
    `/api/v1/multimodal/voices/builtin?organization_id=${encodeURIComponent(organizationId)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ),
  createDesign: (organizationId: string, data: {
    name: string; design_prompt: string; grants: VoiceGrantInput[];
  }) => request<VoiceProfile>(
    `/api/v1/multimodal/voices/design?organization_id=${encodeURIComponent(organizationId)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ),
  createClone: (organizationId: string, data: {
    name: string; sample_file_id: string; evidence_file_id: string;
    rights_holder: string; purpose: string; valid_until: string; confirmed: boolean;
    grants: VoiceGrantInput[];
  }) => request<VoiceProfile>(
    `/api/v1/multimodal/voices/clone?organization_id=${encodeURIComponent(organizationId)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ),
  update: (voiceId: string, data: {
    name?: string; status?: 'active' | 'disabled'; grants?: VoiceGrantInput[];
  }) => request<VoiceProfile>(`/api/v1/multimodal/voices/${voiceId}`, {
    method: 'PATCH', body: JSON.stringify(data),
  }),
  delete: (voiceId: string) => request<void>(`/api/v1/multimodal/voices/${voiceId}`, { method: 'DELETE' }),
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
  test: (id: string) =>
    request<{ status: string; vendor: string; detail: string }>(`/api/v1/providers/${id}/test`, { method: 'POST' }),
  listModels: (id: string) => request<ModelDeployment[]>(`/api/v1/providers/${id}/models`),
  createModel: (id: string, data: ModelDeploymentInput) =>
    request<ModelDeployment>(`/api/v1/providers/${id}/models`, { method: 'POST', body: JSON.stringify(data) }),
  updateModel: (providerId: string, modelId: string, data: Partial<ModelDeploymentInput>) =>
    request<ModelDeployment>(`/api/v1/providers/${providerId}/models/${modelId}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteModel: (providerId: string, modelId: string) =>
    request<void>(`/api/v1/providers/${providerId}/models/${modelId}`, { method: 'DELETE' }),
  testModel: (providerId: string, modelId: string, capability: ModelCapability) =>
    request<{ status: string; capability: string; model_id: string; detail: string }>(
      `/api/v1/providers/${providerId}/models/${modelId}/test/${capability}`,
      { method: 'POST' },
    ),
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
  capabilities?: { read: boolean; create: boolean; manage: boolean; publish: boolean };
}

export interface WorkspaceFile {
  id: string; workspace_id: string; path: string; size: number;
  content_hash: string | null; content: string | null; metadata: Record<string, unknown>;
  extracted_text: string | null; parse_status: 'unparsed' | 'queued' | 'processing' | 'ready' | 'unsupported' | 'failed';
  parse_kind: string | null; parse_error: string | null;
  created_at: string; updated_at: string;
  presentation?: WorkspaceFilePresentation;
}

export interface WorkspaceFilePresentation {
  display_name: string; source_kind: string; source_task_id: string | null;
  source_task_title: string | null; skill_id: string | null;
  skill_display_name: string | null; skill_version: string | null; created_at: string | null;
}

export interface WorkspaceFileListItem {
  id: string; workspace_id: string; path: string; original_filename: string; size: number;
  mime_type: string | null; is_binary: boolean; content_hash: string | null;
  parse_status: 'unparsed' | 'queued' | 'processing' | 'ready' | 'unsupported' | 'failed';
  parse_kind: string | null; parse_error: string | null;
  created_at: string; updated_at: string;
  presentation: WorkspaceFilePresentation;
}

export interface WorkspaceFilePage {
  items: WorkspaceFileListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface WorkspaceFilePreview {
  id: string; path: string; parse_status: WorkspaceFile['parse_status'];
  parse_kind: string | null; parse_error: string | null; extracted_text: string | null;
}

export interface WorkspaceOriginalPreviewSource {
  mode: 'url' | 'blob';
  url: string | null;
  fallback_url: string | null;
  headers: Record<string, string>;
  filename: string;
  mime_type: string;
}

export interface WorkspaceDownloadTicket {
  url: string;
  fallback_url: string | null;
  expires_at: string;
  filename: string;
  mime_type: string;
  etag: string | null;
  size: number;
  headers: Record<string, string>;
}

export interface WorkspacePdfPreviewInfo {
  page_count: number;
  width: number;
  height: number;
}

export interface WorkspaceUploadOptions {
  signal?: AbortSignal;
  onProgress?: (percent: number) => void;
  onUploadComplete?: () => void;
}

async function loadAllWorkspaceFilePages(
  loadPage: (page: number, pageSize: number) => Promise<WorkspaceFilePage>,
): Promise<WorkspaceFileListItem[]> {
  const pageSize = 200;
  const items: WorkspaceFileListItem[] = [];
  for (let page = 1; ; page += 1) {
    const result = await loadPage(page, pageSize);
    items.push(...result.items);
    if (items.length >= result.total || result.items.length === 0) return items;
  }
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

export interface WorkspaceFileVersion {
  id: string; workspace_file_id: string; version_no: number; size: number;
  content_hash: string | null; parse_status: string; parse_kind: string | null;
  parse_error: string | null; created_at: string;
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
  listFilesPage: (wsId: string, page = 1, pageSize = 100) =>
    request<WorkspaceFilePage>(`/api/v1/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`),
  listFiles: (wsId: string) => loadAllWorkspaceFilePages((page, pageSize) =>
    request<WorkspaceFilePage>(`/api/v1/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`)),
  upsertFile: (wsId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    request<WorkspaceFile>(`/api/v1/workspaces/${wsId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  uploadFile: (wsId: string, file: File, path: string, options?: WorkspaceUploadOptions) =>
    uploadAdminWorkspaceFile(wsId, file, path, options),
  getFile: (id: string) => request<WorkspaceFile>(`/api/v1/files/${id}`),
  getFilePreview: (id: string) => request<WorkspaceFilePreview>(`/api/v1/files/${id}/preview`),
  getFileOriginalPreviewSource: (id: string) =>
    request<WorkspaceOriginalPreviewSource>(`/api/v1/files/${id}/original-preview-source`),
  getFilePdfPreviewInfo: (id: string) =>
    request<WorkspacePdfPreviewInfo>(`/api/v1/files/${id}/pdf-preview/info`),
  getFilePdfPreviewPage: (id: string, pageNumber: number) =>
    requestBlob(`/api/v1/files/${id}/pdf-preview/pages/${pageNumber}`, 'ai_infra_token'),
  getFileOriginalPreview: (id: string) => requestBlob(`/api/v1/files/${id}/original-preview`, 'ai_infra_token'),
  downloadFile: (id: string) => requestBlob(`/api/v1/files/${id}/download`, 'ai_infra_token'),
  reparseFile: (id: string) => request<WorkspaceFile>(`/api/v1/files/${id}/reparse`, { method: 'POST' }),
  updateFile: (id: string, data: { content?: string; metadata?: Record<string, unknown> }) =>
    request<WorkspaceFile>(`/api/v1/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFile: (id: string) => request<void>(`/api/v1/files/${id}`, { method: 'DELETE' }),
  listFileVersions: (id: string) => request<WorkspaceFileVersion[]>(`/api/v1/files/${id}/versions`),
  restoreFileVersion: (id: string, versionId: string) =>
    request<WorkspaceFile>(`/api/v1/files/${id}/versions/${versionId}/restore`, { method: 'POST' }),
  listFolders: (wsId: string) => request<WorkspaceFolder[]>(`/api/v1/workspaces/${wsId}/folders`),
  createFolder: (wsId: string, data: { path: string }) =>
    request<WorkspaceFolder>(`/api/v1/workspaces/${wsId}/folders`, { method: 'POST', body: JSON.stringify(data) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/folders/${id}`, { method: 'DELETE' }),
  deleteFolderPath: (wsId: string, path: string) =>
    request<{ folders: number; files: number }>(`/api/v1/workspaces/${wsId}/folder-path?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  bulkDeleteItems: (wsId: string, data: { file_ids: string[]; folder_paths: string[] }) =>
    request<{ deleted_files: number; deleted_folders: number }>(`/api/v1/workspaces/${wsId}/items/bulk-delete`, { method: 'POST', body: JSON.stringify(data) }),
  listTrash: (wsId: string) => request<WorkspaceFile[]>(`/api/v1/workspaces/${wsId}/trash`),
  restoreTrash: (wsId: string, fileId: string) =>
    request<WorkspaceFile>(`/api/v1/workspaces/${wsId}/trash/${fileId}/restore`, { method: 'POST' }),
  listAudit: (wsId: string, limit = 200) =>
    request<WorkspaceAuditEvent[]>(`/api/v1/workspaces/${wsId}/audit?limit=${limit}`),
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

export interface OpenApiPreviewEndpoint {
  name: string; method: string; path: string; description: string;
  params_schema: Record<string, unknown>; response_schema: Record<string, unknown>;
}

export interface OpenApiInspection {
  title: string | null; version: string | null; spec: Record<string, unknown>;
  endpoints: OpenApiPreviewEndpoint[];
}

export const connectors = {
  list: (orgId: string) => request<ToolConnector[]>(`/api/v1/organizations/${orgId}/connectors`),
  get: (id: string) => request<ToolConnector>(`/api/v1/connectors/${id}`),
  create: (orgId: string, data: Partial<ToolConnector> & { auth_config?: Record<string, unknown> }) =>
    request<ToolConnector>(`/api/v1/organizations/${orgId}/connectors`, { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<ToolConnector> & { auth_config?: Record<string, unknown> }) =>
    request<ToolConnector>(`/api/v1/connectors/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) => request<void>(`/api/v1/connectors/${id}`, { method: 'DELETE' }),
  inspectSpec: (orgId: string, data: { url?: string; content?: string }) =>
    request<OpenApiInspection>(`/api/v1/organizations/${orgId}/connectors/inspect-spec`, {
      method: 'POST', body: JSON.stringify(data),
    }),
  importSpec: (id: string) => request<ToolEndpoint[]>(`/api/v1/connectors/${id}/import-spec`, { method: 'POST' }),
  publishSkill: (id: string, data: { name: string; slug: string; description?: string; endpoint_ids: string[] }) =>
    request<SkillFolder>(`/api/v1/connectors/${id}/publish-skill`, {
      method: 'POST', body: JSON.stringify(data),
    }),
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
  active_version_id: string | null;
  is_active: boolean;
  is_installed: boolean;
  description: string | null;
  active_version_no: number | null;
  active_install_status: string | null;
  created_at: string; updated_at: string;
}

export interface SkillVersion {
  id: string; skill_folder_id: string; version_no: number; package_hash: string;
  manifest: Record<string, unknown>; runtime: 'prompt' | 'python' | 'node' | 'agent_skill';
  entrypoint: string | null; is_executable: boolean;
  install_status: 'pending' | 'installing' | 'ready' | 'failed';
  package_format: 'legacy' | 'agent_skill'; script_languages: string[];
  compatibility_warnings: string[];
  python_version: string | null; node_version: string | null;
  builtin_dependencies: Record<string, Record<string, string | null>>;
  installed_dependencies: Record<string, string[]>;
  install_error: string | null; created_at: string; updated_at: string;
}

export interface SkillImportResult { folder: SkillFolder; version: SkillVersion }

export interface SkillScopeNode extends KbNode {
  can_import: boolean;
  can_manage: boolean;
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
  scope_type: string; scope_id: string | null;
  description: string;
  is_executable: boolean;
  install_status: string;
  package_format: string;
}

/** /terminal/workspace-files 返回的工作空间文件轻量摘要（跨全部可访问工作空间，供 @ 引用下拉）。 */
export interface WorkspaceFileSummary {
  id: string; workspace_id: string; workspace_name: string;
  path: string; original_filename: string; presentation: WorkspaceFilePresentation;
  scope_type: string; is_binary: boolean;
}

const SKILL_ARCHIVE_MAX_BYTES = 100 * 1024 * 1024;
const SKILL_FOLDER_MAX_BYTES = 500 * 1024 * 1024;
const SKILL_FOLDER_MAX_FILES = 1000;

function assertSkillArchiveLimit(file: File): void {
  if (file.size > SKILL_ARCHIVE_MAX_BYTES) {
    throw new ApiError(413, 'Skill ZIP 或 Markdown 文件不能超过 100MB');
  }
}

function assertSkillFolderLimits(files: File[]): void {
  if (!files.length || files.length > SKILL_FOLDER_MAX_FILES) {
    throw new ApiError(422, `Skill 文件夹必须包含 1-${SKILL_FOLDER_MAX_FILES} 个文件`);
  }
  const total = files.reduce((sum, file) => sum + file.size, 0);
  if (total > SKILL_FOLDER_MAX_BYTES) {
    throw new ApiError(413, 'Skill 文件夹展开后不能超过 500MB');
  }
}

export const skillStore = {
  listFolders: (orgId: string, scope: ScopeRef) =>
    request<SkillFolder[]>(`/api/v1/organizations/${orgId}/skill-folders?scope_type=${scope.scope_type}&scope_id=${scope.scope_id ?? ''}`),
  createFolder: (orgId: string, data: { name: string; slug: string; scope_type: string; scope_id: string | null }) =>
    request<SkillFolder>(`/api/v1/organizations/${orgId}/skill-folders`, { method: 'POST', body: JSON.stringify(data) }),
  updateFolder: (id: string, data: { name?: string; slug?: string; is_active?: boolean }) =>
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
  importPackage: (orgId: string, file: File, scope: ScopeRef) => {
    assertSkillArchiveLimit(file);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('scope_type', scope.scope_type);
    if (scope.scope_id) fd.append('scope_id', scope.scope_id);
    return request<SkillImportResult>(`/api/v1/organizations/${orgId}/skill-folders/import`, {
      method: 'POST', body: fd, headers: {},
    });
  },
  importPackageFolder: (orgId: string, files: File[], scope: ScopeRef) => {
    assertSkillFolderLimits(files);
    const fd = new FormData();
    files.forEach((file) => {
      fd.append('files', file, file.name);
      fd.append('relative_paths', file.webkitRelativePath || file.name);
    });
    fd.append('scope_type', scope.scope_type);
    if (scope.scope_id) fd.append('scope_id', scope.scope_id);
    return request<SkillImportResult>(`/api/v1/organizations/${orgId}/skill-folders/import`, {
      method: 'POST', body: fd, headers: {},
    });
  },
  listVersions: (folderId: string) => request<SkillVersion[]>(`/api/v1/skill-folders/${folderId}/versions`),
  retryVersion: (versionId: string) =>
    request<SkillVersion>(`/api/v1/skill-versions/${versionId}/retry`, { method: 'POST' }),
  activateVersion: (versionId: string) =>
    request<SkillVersion>(`/api/v1/skill-versions/${versionId}/activate`, { method: 'POST' }),
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
  const isMultipart = options?.body instanceof FormData;
  const headers: Record<string, string> = isMultipart ? {} : { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const { headers: optionHeaders, ...requestOptions } = options ?? {};
  return fetch(`${BASE_URL}${path}`, {
    ...requestOptions,
    headers: { ...headers, ...(optionHeaders as Record<string, string> | undefined) },
  })
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
  department_ids: string[];
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
  capabilities: Record<string, { vision: boolean }>;
  vision_fallback_available: boolean;
  image_generation_available: boolean;
}

export interface WorkspaceAuditEvent {
  id: number; workspace_id: string; workspace_file_id: string | null;
  version_id: string | null; action: string; actor_display_name: string | null;
  metadata: Record<string, unknown>; created_at: string;
}

// Keep the SaaS API out of the large-file data path. Files above 1MB go
// directly from the browser to OSS, reducing one full network hop and freeing
// backend workers for metadata validation and parsing.
const WORKSPACE_PROXY_UPLOAD_BYTES = 1 * 1024 * 1024;
export const WORKSPACE_MAX_FILE_BYTES = 5 * 1024 * 1024 * 1024;
export const WORKSPACE_AI_PARSE_MAX_FILE_BYTES = 100 * 1024 * 1024;

interface DirectUploadSession {
  id: string; method: 'PUT' | 'MULTIPART'; url: string | null; headers: Record<string, string>;
  fallback_url: string | null;
  expires_at: string; max_file_bytes: number;
  part_size: number | null; expected_parts: number | null;
}

interface MultipartPartSigned {
  part_number: number; method: 'PUT'; url: string; fallback_url: string | null;
  headers: Record<string, string>; expires_in: number;
}

interface MultipartUploadPart {
  part_number: number; etag: string; size: number;
}

interface MultipartUploadStatus {
  status: string; part_size: number; expected_parts: number;
  uploaded_parts: MultipartUploadPart[]; expires_at: string;
}

interface MultipartPartReceipt {
  part_number: number; etag: string;
}

const OSS_MAX_ACTIVE_REQUESTS = 10;
let activeOssRequests = 0;
const ossRequestWaiters: Array<() => void> = [];

async function acquireOssRequestSlot() {
  if (activeOssRequests >= OSS_MAX_ACTIVE_REQUESTS) {
    await new Promise<void>((resolve) => ossRequestWaiters.push(resolve));
  }
  activeOssRequests += 1;
  return () => {
    activeOssRequests = Math.max(0, activeOssRequests - 1);
    ossRequestWaiters.shift()?.();
  };
}

function weakNetworkPreferred() {
  const connection = (navigator as Navigator & {
    connection?: { effectiveType?: string; saveData?: boolean };
  }).connection;
  return Boolean(connection?.saveData || ['slow-2g', '2g'].includes(connection?.effectiveType ?? ''));
}

async function putSignedWorkspaceFileAttempt(
  session: DirectUploadSession, file: File, url: string | null, options?: WorkspaceUploadOptions,
): Promise<string | null> {
  const release = await acquireOssRequestSlot();
  try {
    return await new Promise((resolve, reject) => {
    if (!url) {
      reject(new ApiError(500, '对象存储上传地址缺失'));
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.timeout = 120_000;
    Object.entries(session.headers || {}).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        options?.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        options?.onUploadComplete?.();
        resolve(xhr.getResponseHeader('ETag'));
        return;
      }
      const detail = xhr.status === 403
        ? '上传凭证已失效，请重新选择文件再试'
        : `对象存储直传失败（HTTP ${xhr.status || '未知'}）`;
      reject(new ApiError(xhr.status, detail));
    };
    xhr.onerror = () => reject(new ApiError(0, 'OSS 直传网络错误'));
    xhr.ontimeout = () => reject(new ApiError(408, 'OSS 直传超时，正在切换线路重试'));
    xhr.onabort = () => reject(new DOMException('上传已取消', 'AbortError'));
    if (options?.signal) {
      if (options.signal.aborted) {
        reject(new DOMException('上传已取消', 'AbortError'));
        return;
      }
      options.signal.addEventListener('abort', () => xhr.abort(), { once: true });
    }
    xhr.send(file);
    });
  } finally {
    release();
  }
}

async function putSignedWorkspaceFile(
  session: DirectUploadSession, file: File, options?: WorkspaceUploadOptions,
): Promise<string | null> {
  const maxAttempts = 3;
  let lastError: unknown;
  let timeoutCount = 0;
  let useFallback = false;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      const target = useFallback && session.fallback_url ? session.fallback_url : session.url;
      return await putSignedWorkspaceFileAttempt(session, file, target, options);
    } catch (error) {
      lastError = error;
      if ((error as Error).name === 'AbortError') throw error;
      const status = error instanceof ApiError ? error.status : 0;
      if (status === 408) timeoutCount += 1;
      if (status === 0 || status === 502 || status === 504 || timeoutCount >= 2) useFallback = true;
      const retryable = status === 0 || status === 408 || status === 429 || status >= 500;
      if (!retryable || attempt === maxAttempts) throw error;
      options?.onProgress?.(0);
      await new Promise((resolve) => window.setTimeout(resolve, attempt * 800));
    }
  }
  throw lastError;
}

async function putMultipartPartAttempt(
  signed: MultipartPartSigned,
  url: string,
  chunk: Blob,
  signal: AbortSignal,
  onProgress: (loaded: number) => void,
): Promise<void> {
  const release = await acquireOssRequestSlot();
  try {
    return await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    // A stalled cross-region connection must not occupy one worker forever.
    // Retrying obtains a fresh signed URL and resumes only this part.
    xhr.timeout = 120_000;
    Object.entries(signed.headers || {}).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(chunk.size);
        resolve();
        return;
      }
      reject(new ApiError(xhr.status, `分片 ${signed.part_number} 上传失败（HTTP ${xhr.status || '未知'}）`));
    };
    xhr.onerror = () => reject(new ApiError(0, `分片 ${signed.part_number} 网络上传失败`));
    xhr.ontimeout = () => reject(new ApiError(408, `分片 ${signed.part_number} 上传超时，正在重试`));
    xhr.onabort = () => reject(new DOMException('上传已取消', 'AbortError'));
    if (signal.aborted) {
      reject(new DOMException('上传已取消', 'AbortError'));
      return;
    }
    signal.addEventListener('abort', () => xhr.abort(), { once: true });
    xhr.send(chunk);
    });
  } finally {
    release();
  }
}

async function uploadMultipartWorkspaceFile(
  session: DirectUploadSession,
  file: File,
  signPart: (partNumber: number) => Promise<MultipartPartSigned>,
  getStatus: () => Promise<MultipartUploadStatus>,
  options?: WorkspaceUploadOptions,
): Promise<MultipartPartReceipt[]> {
  const partSize = session.part_size || 0;
  const expectedParts = session.expected_parts || Math.ceil(file.size / Math.max(partSize, 1));
  if (partSize <= 0 || expectedParts <= 0) throw new ApiError(500, '对象存储分片参数无效');

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  options?.signal?.addEventListener('abort', abortFromCaller, { once: true });
  if (options?.signal?.aborted) controller.abort();

  const uploadedBytes = new Map<number, number>();
  const reportProgress = () => {
    const loaded = Array.from(uploadedBytes.values()).reduce((sum, bytes) => sum + bytes, 0);
    options?.onProgress?.(Math.min(99, Math.round((loaded / file.size) * 100)));
  };
  let nextPart = 1;
  const uploadOne = async (partNumber: number) => {
    const start = (partNumber - 1) * partSize;
    const chunk = file.slice(start, Math.min(start + partSize, file.size));
    let lastError: unknown;
    let timeoutCount = 0;
    let useFallback = false;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const signed = await signPart(partNumber);
        const target = useFallback && signed.fallback_url ? signed.fallback_url : signed.url;
        await putMultipartPartAttempt(signed, target, chunk, controller.signal, (loaded) => {
          uploadedBytes.set(partNumber, loaded);
          reportProgress();
        });
        return;
      } catch (error) {
        lastError = error;
        if ((error as Error).name === 'AbortError') throw error;
        const status = error instanceof ApiError ? error.status : 0;
        if (status === 408) timeoutCount += 1;
        if (status === 0 || status === 502 || status === 504 || timeoutCount >= 2) useFallback = true;
        const retryable = status === 0 || status === 408 || status === 429 || status >= 500;
        if (!retryable || attempt === 3) throw error;
        uploadedBytes.set(partNumber, 0);
        reportProgress();
        await new Promise((resolve) => window.setTimeout(resolve, attempt * 500));
      }
    }
    throw lastError;
  };
  const worker = async () => {
    while (!controller.signal.aborted) {
      const partNumber = nextPart;
      nextPart += 1;
      if (partNumber > expectedParts) return;
      await uploadOne(partNumber);
    }
  };

  try {
    await Promise.all(Array.from({ length: Math.min(4, expectedParts) }, () => worker()));
    const status = await getStatus();
    const uploaded = [...status.uploaded_parts].sort((a, b) => a.part_number - b.part_number);
    if (uploaded.length !== expectedParts) {
      throw new ApiError(409, `分片上传未完成（${uploaded.length}/${expectedParts}）`);
    }
    options?.onProgress?.(100);
    options?.onUploadComplete?.();
    return uploaded.map((part) => ({ part_number: part.part_number, etag: part.etag }));
  } catch (error) {
    controller.abort();
    throw error;
  } finally {
    options?.signal?.removeEventListener('abort', abortFromCaller);
  }
}

async function uploadTerminalWorkspaceFile(
  wsId: string, file: File, path: string, options?: WorkspaceUploadOptions,
): Promise<WorkspaceFile> {
  if (file.size > WORKSPACE_MAX_FILE_BYTES) throw new ApiError(413, '文件超过 5GB 存储上限');
  if (file.size <= WORKSPACE_PROXY_UPLOAD_BYTES) {
    return uploadWorkspaceFile(
      `/api/v1/terminal/workspaces/${wsId}/files/upload`, file, path, USER_TOKEN_KEY, options,
    );
  }
  const initiate = (weakNetwork: boolean) => userRequest<DirectUploadSession>(
    `/api/v1/terminal/workspaces/${wsId}/uploads/initiate`, { method: 'POST', body: JSON.stringify({
      path, filename: file.name, content_type: file.type || 'application/octet-stream',
      size: file.size, weak_network: weakNetwork,
    }) },
  );
  let weakNetwork = weakNetworkPreferred();
  let session = await initiate(weakNetwork);
  let retriedInWeakMode = false;
  while (true) {
  try {
    if (session.method === 'MULTIPART') {
      const parts = await uploadMultipartWorkspaceFile(
        session,
        file,
        (partNumber) => userRequest<MultipartPartSigned>(
          `/api/v1/terminal/uploads/${session.id}/parts/${partNumber}/sign`, { method: 'POST' },
        ),
        () => userRequest<MultipartUploadStatus>(`/api/v1/terminal/uploads/${session.id}`),
        options,
      );
      return await userRequest<WorkspaceFile>(`/api/v1/terminal/uploads/${session.id}/complete`, {
        method: 'POST', body: JSON.stringify({ parts }),
      });
    }
    const etag = await putSignedWorkspaceFile(session, file, options);
    return await userRequest<WorkspaceFile>(`/api/v1/terminal/uploads/${session.id}/complete`, {
      method: 'POST', body: JSON.stringify({ etag }),
    });
  } catch (error) {
    void userRequest<void>(`/api/v1/terminal/uploads/${session.id}`, { method: 'DELETE' }).catch(() => undefined);
    const status = error instanceof ApiError ? error.status : 0;
    if (session.method === 'MULTIPART' && !weakNetwork && !retriedInWeakMode && (status === 0 || status === 408)) {
      weakNetwork = true;
      retriedInWeakMode = true;
      session = await initiate(true);
      options?.onProgress?.(0);
      continue;
    }
    throw error;
  }
  }
}

async function uploadAdminWorkspaceFile(
  wsId: string, file: File, path: string, options?: WorkspaceUploadOptions,
): Promise<WorkspaceFile> {
  if (file.size > WORKSPACE_MAX_FILE_BYTES) throw new ApiError(413, '文件超过 5GB 存储上限');
  if (file.size <= WORKSPACE_PROXY_UPLOAD_BYTES) {
    return uploadWorkspaceFile(
      `/api/v1/workspaces/${wsId}/files/upload`, file, path, 'ai_infra_token', options,
    );
  }
  const initiate = (weakNetwork: boolean) => request<DirectUploadSession>(`/api/v1/workspaces/${wsId}/uploads/initiate`, {
    method: 'POST', body: JSON.stringify({
      path, filename: file.name, content_type: file.type || 'application/octet-stream',
      size: file.size, weak_network: weakNetwork,
    }),
  });
  let weakNetwork = weakNetworkPreferred();
  let session = await initiate(weakNetwork);
  let retriedInWeakMode = false;
  while (true) {
  try {
    if (session.method === 'MULTIPART') {
      const parts = await uploadMultipartWorkspaceFile(
        session,
        file,
        (partNumber) => request<MultipartPartSigned>(
          `/api/v1/workspace-uploads/${session.id}/parts/${partNumber}/sign`, { method: 'POST' },
        ),
        () => request<MultipartUploadStatus>(`/api/v1/workspace-uploads/${session.id}`),
        options,
      );
      return await request<WorkspaceFile>(`/api/v1/workspace-uploads/${session.id}/complete`, {
        method: 'POST', body: JSON.stringify({ parts }),
      });
    }
    const etag = await putSignedWorkspaceFile(session, file, options);
    return await request<WorkspaceFile>(`/api/v1/workspace-uploads/${session.id}/complete`, {
      method: 'POST', body: JSON.stringify({ etag }),
    });
  } catch (error) {
    void request<void>(`/api/v1/workspace-uploads/${session.id}`, { method: 'DELETE' }).catch(() => undefined);
    const status = error instanceof ApiError ? error.status : 0;
    if (session.method === 'MULTIPART' && !weakNetwork && !retriedInWeakMode && (status === 0 || status === 408)) {
      weakNetwork = true;
      retriedInWeakMode = true;
      session = await initiate(true);
      options?.onProgress?.(0);
      continue;
    }
    throw error;
  }
  }
}

export interface TaskConfig {
  workspace_id: string | null;
  // RAG 固定来自本次选中的智能体；Skill 绑定只是默认推荐，聊天可本轮调用其他有权 Skill。
  model_alias: string | null;
  /** 执行模式：craft（自主多步执行）/ ask（只读单轮问答）/ plan（出方案不执行） */
  exec_mode: 'craft' | 'ask' | 'plan';
  /** 终端「选智能体」逐次运行覆盖（不落库）：UUID=该次用此智能体；null=通用智能体（不绑模板）。
   *  注意：此字段仅前端态，不写入 task.config；run 请求里随消息一起发送，由后端 exclude_unset 判定覆盖。 */
  template_agent_id?: string | null;
  /** 企业业务应用上下文；为空时保持原有通用助手行为。 */
  application_id?: string | null;
}

export type EnterpriseApplicationPermission =
  | 'view' | 'ai_query' | 'ai_create' | 'ai_update' | 'ai_delete' | 'ai_approve' | 'export';
export type EnterpriseApplicationScope = 'organization' | 'role' | 'department' | 'team' | 'user';
export type EnterpriseApplicationTarget = 'tool_endpoint' | 'data_interface' | 'skill_folder';
export type EnterpriseApplicationOperation = 'query' | 'create' | 'update' | 'delete' | 'export' | 'approve';

export interface EnterpriseApplicationModuleAccess {
  role: string;
  permissions: EnterpriseApplicationPermission[];
  action_keys: string[];
  page_access: Record<string, {
    permissions: EnterpriseApplicationPermission[];
    action_keys: string[];
    /** 平台侧 AI 总开关；不影响员工在页面内使用已授权按钮。 */
    ai_enabled?: boolean;
  }>;
}

export interface EnterpriseApplicationGrant {
  id: string; application_id: string; organization_id: string;
  scope_type: EnterpriseApplicationScope; scope_id: string | null;
  permissions: EnterpriseApplicationPermission[];
  module_keys: string[];
  module_access: Record<string, EnterpriseApplicationModuleAccess>;
  created_at: string; updated_at: string;
}

export interface EnterpriseApplicationToolBinding {
  id: string; application_id: string; organization_id: string;
  target_type: EnterpriseApplicationTarget; target_id: string;
  operation: EnterpriseApplicationOperation; is_active: boolean;
  created_at: string; updated_at: string;
}

export interface EnterpriseApplication {
  id: string; organization_id: string; name: string; slug: string;
  description: string | null; icon_url: string | null; entry_url: string;
  display_mode: 'embedded' | 'external'; sort_order: number; is_active: boolean;
  assistant_enabled: boolean; assistant_prompt: string | null;
  assistant_config: Record<string, unknown>; health_status: string;
  grants: EnterpriseApplicationGrant[];
  tool_bindings: EnterpriseApplicationToolBinding[];
  created_at: string; updated_at: string;
}

export type EnterpriseApplicationInput = Pick<EnterpriseApplication,
  'name' | 'slug' | 'entry_url' | 'display_mode' | 'sort_order' | 'is_active' | 'assistant_enabled'
> & Partial<Pick<EnterpriseApplication, 'description' | 'icon_url' | 'assistant_prompt' | 'assistant_config'>>;

export interface TerminalEnterpriseApplication {
  id: string; name: string; slug: string; description: string | null;
  icon_url: string | null; display_mode: 'embedded' | 'external';
  sort_order: number; assistant_enabled: boolean;
  permissions: EnterpriseApplicationPermission[];
  module_keys: string[];
  modules: Array<{ module_key: string; name: string }>;
}

export interface EnterpriseApplicationLaunch {
  application_id: string; url: string; display_mode: 'embedded' | 'external';
  permissions: EnterpriseApplicationPermission[];
  module_keys: string[];
  module_key: string | null;
  modules: Array<{ module_key: string; name: string }>;
}

export interface EnterpriseApplicationManifestDepartment {
  key: string; name: string; role: string;
  actionKeys?: string[]; pageKeys?: string[];
  platformDepartmentId?: string | null; matchStatus?: 'matched' | 'unresolved';
}

export interface EnterpriseApplicationManifestAccessRole {
  roleKey: string; name: string; description?: string;
  suggestedDepartmentKey?: string | null;
  pageKeys: string[]; actionKeys: string[];
}

export interface EnterpriseApplicationManifestAction {
  actionKey: string; name: string; description?: string;
  operation: EnterpriseApplicationOperation; aiEnabled: boolean;
  requiresConfirmation: boolean; inputSchema: Record<string, unknown>;
  resultSchema: Record<string, unknown>;
}

export interface EnterpriseApplicationManifestPage {
  pageKey: string; name: string; routePattern: string; queryActionKey?: string | null;
  actionKeys: string[]; contextSchema: Record<string, unknown>;
}

export interface EnterpriseApplicationManifestModule {
  moduleKey: string; name: string; route: string;
  departments: EnterpriseApplicationManifestDepartment[];
  accessRoles?: EnterpriseApplicationManifestAccessRole[];
  pages: EnterpriseApplicationManifestPage[];
  actions: EnterpriseApplicationManifestAction[];
}

export interface EnterpriseApplicationIntegration {
  application_id: string; manifest_url: string; events_url: string | null;
  protocol_version: number; manifest: Record<string, unknown>;
  modules: EnterpriseApplicationManifestModule[];
  cursor_sequence: number; sync_enabled: boolean;
  sync_status: 'unconfigured' | 'ready' | 'syncing' | 'healthy' | 'error';
  token_configured: boolean; last_manifest_sync_at: string | null;
  last_event_sync_at: string | null; last_error: string | null;
}

export interface EnterpriseApplicationDiscovery {
  entry_url: string; manifest_url: string; health_url: string;
  health_status: 'healthy' | 'unhealthy'; protocol_version: number;
  suggested_name: string; suggested_slug: string;
  manifest: Record<string, unknown>; modules: EnterpriseApplicationManifestModule[];
}

export interface EnterpriseApplicationAction {
  id: string; application_id: string; module_key: string; action_key: string;
  name: string; description: string | null; operation: EnterpriseApplicationOperation;
  ai_enabled: boolean; requires_confirmation: boolean;
  input_schema: Record<string, unknown>; result_schema: Record<string, unknown>;
  is_active: boolean; created_at: string; updated_at: string;
}

export interface EnterpriseApplicationActionResult {
  request_id: string;
  status: 'pending' | 'executing' | 'completed' | 'rejected' | 'expired' | 'failed';
  confirmation_id: string | null; result: Record<string, unknown>; error: string | null;
  provenance: Record<string, unknown>;
}

export interface EnterpriseApplicationActionRequest {
  id: string; application_id: string; action_id: string; request_id: string;
  module_key: string; page_key: string | null; status: EnterpriseApplicationActionResult['status'];
  params: Record<string, unknown>;
  expires_at: string; resolved_at: string | null; result: Record<string, unknown>;
  error: string | null; action: EnterpriseApplicationAction;
  created_at: string; updated_at: string;
}

export interface EnterpriseApplicationEventRoute {
  id: string; application_id: string; name: string; event_type: string;
  module_key: string | null; target_scope_type: EnterpriseApplicationScope;
  target_scope_id: string | null; target_application_id: string | null; target_module_key: string | null;
  is_active: boolean; created_at: string; updated_at: string;
}

export interface CrossDepartmentWorkItem {
  id: string; source_application_id: string; source_event_id: string;
  title: string; status: 'open' | 'done'; target_scope_type: string;
  target_scope_id: string | null; target_module_key: string | null;
  source_context: Record<string, unknown>; created_at: string; updated_at: string;
}

export interface EnterpriseApplicationCapability {
  binding_id: string;
  target_type: EnterpriseApplicationTarget;
  target_id: string;
  operation: EnterpriseApplicationOperation;
  name: string;
  source_name: string;
  description: string | null;
  method: string | null;
  path: string | null;
  binding_active: boolean;
  target_active: boolean;
  health_status: string | null;
}

export interface EnterpriseApplicationRecentCall {
  id: number;
  capability_name: string;
  method: string | null;
  path: string | null;
  status: 'success' | 'failed';
  status_code: number | null;
  latency_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface EnterpriseApplicationOverview {
  application_id: string;
  operation_counts: Record<EnterpriseApplicationOperation, number>;
  active_capability_count: number;
  direct_capability_count: number;
  skill_binding_count: number;
  capabilities: EnterpriseApplicationCapability[];
  recent_calls: EnterpriseApplicationRecentCall[];
}

export const enterpriseApplications = {
  list: (orgId: string) => request<EnterpriseApplication[]>(`/api/v1/organizations/${orgId}/applications`),
  get: (id: string) => request<EnterpriseApplication>(`/api/v1/applications/${id}`),
  overview: (id: string) => request<EnterpriseApplicationOverview>(`/api/v1/applications/${id}/overview`),
  create: (orgId: string, data: EnterpriseApplicationInput) =>
    request<EnterpriseApplication>(`/api/v1/organizations/${orgId}/applications`, {
      method: 'POST', body: JSON.stringify(data),
    }),
  discover: (orgId: string, data: { base_url: string; auth_token?: string }) =>
    request<EnterpriseApplicationDiscovery>(`/api/v1/organizations/${orgId}/applications/discover`, {
      method: 'POST', body: JSON.stringify(data),
    }),
  update: (id: string, data: Partial<EnterpriseApplicationInput>) =>
    request<EnterpriseApplication>(`/api/v1/applications/${id}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),
  delete: (id: string) => request<void>(`/api/v1/applications/${id}`, { method: 'DELETE' }),
  replaceGrants: (id: string, grants: Array<{
    scope_type: EnterpriseApplicationScope; scope_id: string | null;
    permissions: EnterpriseApplicationPermission[];
    module_keys?: string[];
    module_access?: Record<string, EnterpriseApplicationModuleAccess>;
  }>) => request<EnterpriseApplication>(`/api/v1/applications/${id}/grants`, {
    method: 'PUT', body: JSON.stringify({ grants }),
  }),
  replaceToolBindings: (id: string, bindings: Array<{
    target_type: EnterpriseApplicationTarget; target_id: string;
    operation: EnterpriseApplicationOperation; is_active: boolean;
  }>) => request<EnterpriseApplication>(`/api/v1/applications/${id}/tool-bindings`, {
    method: 'PUT', body: JSON.stringify({ bindings }),
  }),
  test: (id: string) => request<{ status: 'healthy' | 'unhealthy'; status_code: number | null; detail: string | null }>(
    `/api/v1/applications/${id}/test`, { method: 'POST' },
  ),
  integration: (id: string) => request<EnterpriseApplicationIntegration>(`/api/v1/applications/${id}/integration`),
  configureIntegration: (id: string, data: {
    manifest_url: string; auth_token?: string; clear_auth_token?: boolean; sync_enabled: boolean;
  }) => request<EnterpriseApplicationIntegration>(`/api/v1/applications/${id}/integration`, {
    method: 'PUT', body: JSON.stringify(data),
  }),
  syncIntegration: (id: string) => request<{
    status: 'healthy' | 'error'; manifest_updated: boolean; received_events: number;
    created_work_items: number; delivered_events: number; cursor_sequence: number; detail: string | null;
  }>(`/api/v1/applications/${id}/integration/sync`, { method: 'POST' }),
  actions: (id: string) => request<EnterpriseApplicationAction[]>(`/api/v1/applications/${id}/actions`),
  eventRoutes: (id: string) => request<EnterpriseApplicationEventRoute[]>(`/api/v1/applications/${id}/event-routes`),
  replaceEventRoutes: (id: string, routes: Array<Omit<EnterpriseApplicationEventRoute, 'id' | 'application_id' | 'created_at' | 'updated_at'>>) =>
    request<EnterpriseApplicationEventRoute[]>(`/api/v1/applications/${id}/event-routes`, {
      method: 'PUT', body: JSON.stringify({ routes }),
    }),
};

export interface TerminalAgent {
  id: string; name: string; slug: string;
  scope_type: string; scope_id: string | null;
  model_alias: string; description: string | null;
  skill_ids: string[];
  rag_collection_ids: string[];
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
  match_excerpt?: string | null;
}

export interface TerminalTaskMessage {
  id: string;
  task_id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  execution_verification: {
    status: 'verified' | 'partial' | 'failed' | 'legacy_unverified';
    tool_calls: number;
    succeeded: number;
    failed: number;
  } | null;
}

export interface TerminalTaskWithMessages extends TerminalTask {
  messages: TerminalTaskMessage[];
  /** 该任务最新一次 run 的状态（queued/running/success/error/cancelled/timeout/busy）。
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
  applications: () => userRequest<TerminalEnterpriseApplication[]>('/api/v1/terminal/applications'),
  launchApplication: (id: string, moduleKey?: string) => userRequest<EnterpriseApplicationLaunch>(
    `/api/v1/terminal/applications/${id}/launch${moduleKey ? `?module_key=${encodeURIComponent(moduleKey)}` : ''}`,
    { method: 'POST', cache: 'no-store' },
  ),
  invokeApplicationAction: (
    id: string, actionKey: string, data: { module_key: string; params: Record<string, unknown>; request_id?: string },
  ) => userRequest<EnterpriseApplicationActionResult>(
    `/api/v1/terminal/applications/${id}/actions/${encodeURIComponent(actionKey)}`,
    { method: 'POST', body: JSON.stringify(data) },
  ),
  applicationActionConfirmations: () => userRequest<EnterpriseApplicationActionRequest[]>(
    '/api/v1/terminal/application-action-confirmations',
  ),
  resolveApplicationAction: (id: string, decision: 'approve' | 'reject') =>
    userRequest<EnterpriseApplicationActionResult>(
      `/api/v1/terminal/application-action-confirmations/${id}/${decision}`,
      { method: 'POST' },
    ),
  crossDepartmentWorkItems: () => userRequest<CrossDepartmentWorkItem[]>(
    '/api/v1/terminal/cross-department-work-items',
  ),
  updateCrossDepartmentWorkItem: (id: string, status: 'open' | 'done') =>
    userRequest<CrossDepartmentWorkItem>(`/api/v1/terminal/cross-department-work-items/${id}`, {
      method: 'PATCH', body: JSON.stringify({ status }),
    }),
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
  skillScopes: () => userRequest<SkillScopeNode[]>('/api/v1/terminal/skill-scopes'),
  importSkill: (file: File, scope: { scope_type: string; scope_id?: string | null }) => {
    assertSkillArchiveLimit(file);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('scope_type', scope.scope_type);
    if (scope.scope_id) fd.append('scope_id', scope.scope_id);
    return userRequest<SkillImportResult>('/api/v1/terminal/skills/import', { method: 'POST', body: fd });
  },
  importSkillFolder: (files: File[], scope: { scope_type: string; scope_id?: string | null }) => {
    assertSkillFolderLimits(files);
    const fd = new FormData();
    files.forEach((file) => {
      fd.append('files', file, file.name);
      fd.append('relative_paths', file.webkitRelativePath || file.name);
    });
    fd.append('scope_type', scope.scope_type);
    if (scope.scope_id) fd.append('scope_id', scope.scope_id);
    return userRequest<SkillImportResult>('/api/v1/terminal/skills/import', { method: 'POST', body: fd });
  },
  listSkillVersions: (folderId: string) =>
    userRequest<SkillVersion[]>(`/api/v1/terminal/skills/${folderId}/versions`),
  retrySkillVersion: (versionId: string) =>
    userRequest<SkillVersion>(`/api/v1/terminal/skill-versions/${versionId}/retry`, { method: 'POST' }),
  activateSkillVersion: (versionId: string) =>
    userRequest<SkillVersion>(`/api/v1/terminal/skill-versions/${versionId}/activate`, { method: 'POST' }),
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
  listTasks: (q?: string) => userRequest<TerminalTask[]>(`/api/v1/terminal/tasks${q?.trim() ? `?q=${encodeURIComponent(q.trim())}` : ''}`),
  createTask: (data: { title?: string; message: string; config: TaskConfig }) =>
    userRequest<TerminalTask>('/api/v1/terminal/tasks', { method: 'POST', body: JSON.stringify(data) }),
  getTask: (id: string) => userRequest<TerminalTaskWithMessages>(`/api/v1/terminal/tasks/${id}`),
  updateTask: (id: string, data: Partial<{ title: string; status: string; config: TaskConfig }>) =>
    userRequest<TerminalTask>(`/api/v1/terminal/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTask: (id: string) => userRequest<void>(`/api/v1/terminal/tasks/${id}`, { method: 'DELETE' }),
  /** 删除一整轮对话（user+assistant 消息），并清理仅本轮产出、未被后续轮次覆盖的工作空间文件。 */
  deleteTaskMessage: (taskId: string, messageId: string) =>
    userRequest<void>(`/api/v1/terminal/tasks/${taskId}/messages/${messageId}`, { method: 'DELETE' }),
  runTask: (
    id: string, message: string, template_agent_id?: string | null,
    attachment_file_ids: string[] = [], invoked_skill_ids: string[] = [],
    application_id?: string | null, page_context: Record<string, unknown> = {},
  ) =>
    userRequest<{ assistant: string; steps: unknown[]; usage: Record<string, number>; run_id: number; latency_ms: number }>(
      `/api/v1/terminal/tasks/${id}/run`,
      { method: 'POST', body: JSON.stringify({ message, stream: false, template_agent_id: template_agent_id ?? null, attachment_file_ids, invoked_skill_ids, application_id: application_id ?? null, page_context }) },
    ),
  /** 流式执行：返回原始 Response，由调用方解析 SSE（仿 AgentPlayground）。
   *  template_agent_id 逐次覆盖（不落库）：undefined=沿用 task.config；null=通用；UUID=该次用此智能体。 */
  runTaskStream: (
    id: string, message: string, signal: AbortSignal,
    template_agent_id?: string | null, attachment_file_ids: string[] = [],
    invoked_skill_ids: string[] = [], application_id?: string | null,
    page_context: Record<string, unknown> = {},
  ) =>
    fetch(`${BASE_URL}/api/v1/terminal/tasks/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem(USER_TOKEN_KEY) || ''}` },
      body: JSON.stringify({ message, stream: true, template_agent_id: template_agent_id ?? null, attachment_file_ids, invoked_skill_ids, application_id: application_id ?? null, page_context }),
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
  listWsFilesPage: (wsId: string, page = 1, pageSize = 100) =>
    userRequest<WorkspaceFilePage>(`/api/v1/terminal/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`),
  listWsFiles: (wsId: string) => loadAllWorkspaceFilePages((page, pageSize) =>
    userRequest<WorkspaceFilePage>(`/api/v1/terminal/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`)),
  /** 用户可访问的全部工作空间文件（组织/部门/团队/个人并集），供任务输入框 @ 引用下拉。 */
  listAllWsFiles: () => userRequest<WorkspaceFileSummary[]>('/api/v1/terminal/workspace-files'),
  upsertWsFile: (wsId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/workspaces/${wsId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  uploadWsFile: (wsId: string, file: File, path: string, options?: WorkspaceUploadOptions) =>
    uploadTerminalWorkspaceFile(wsId, file, path, options),
  getWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`),
  getWsFilePreview: (id: string) => userRequest<WorkspaceFilePreview>(`/api/v1/terminal/files/${id}/preview`),
  getWsFileOriginalPreviewSource: (id: string) =>
    userRequest<WorkspaceOriginalPreviewSource>(`/api/v1/terminal/files/${id}/original-preview-source`),
  getWsFileDownloadTicket: (id: string) =>
    userRequest<WorkspaceDownloadTicket>(`/api/v1/terminal/files/${id}/download-ticket`, { method: 'POST' }),
  getWsFilePdfPreviewInfo: (id: string) =>
    userRequest<WorkspacePdfPreviewInfo>(`/api/v1/terminal/files/${id}/pdf-preview/info`),
  getWsFilePdfPreviewPage: (id: string, pageNumber: number) =>
    requestBlob(`/api/v1/terminal/files/${id}/pdf-preview/pages/${pageNumber}`, USER_TOKEN_KEY),
  getWsFileOriginalPreview: (id: string, signal?: AbortSignal) => requestBlob(`/api/v1/terminal/files/${id}/original-preview`, USER_TOKEN_KEY, signal),
  downloadWsFile: (id: string, signal?: AbortSignal) => requestBlob(`/api/v1/terminal/files/${id}/download`, USER_TOKEN_KEY, signal),
  reparseWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/reparse`, { method: 'POST' }),
  updateWsFile: (id: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteWsFile: (id: string) => userRequest<void>(`/api/v1/terminal/files/${id}`, { method: 'DELETE' }),
  listWsFileVersions: (id: string) => userRequest<Array<{
    id: string; workspace_file_id: string; version_no: number; size: number;
    content_hash: string | null; parse_status: string; parse_kind: string | null;
    parse_error: string | null; created_at: string;
  }>>(`/api/v1/terminal/files/${id}/versions`),
  restoreWsFileVersion: (id: string, versionId: string) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/versions/${versionId}/restore`, { method: 'POST' }),
  listWsTrash: (wsId: string) => userRequest<WorkspaceFile[]>(`/api/v1/terminal/workspaces/${wsId}/trash`),
  listWsAudit: (wsId: string, limit = 200) =>
    userRequest<WorkspaceAuditEvent[]>(`/api/v1/terminal/workspaces/${wsId}/audit?limit=${limit}`),
  restoreWsTrash: (wsId: string, fileId: string) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/workspaces/${wsId}/trash/${fileId}/restore`, { method: 'POST' }),
  publishWsFile: (id: string, targetWorkspaceId: string, targetPath?: string) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/publish`, {
      method: 'POST', body: JSON.stringify({ target_workspace_id: targetWorkspaceId, target_path: targetPath || null }),
    }),
  createWsShare: (id: string, expiresInSeconds = 7 * 24 * 3600) =>
    userRequest<{ url: string; expires_at: string }>(`/api/v1/terminal/files/${id}/shares`, {
      method: 'POST', body: JSON.stringify({ expires_in_seconds: expiresInSeconds }),
    }),
  listWsFolders: (wsId: string) => userRequest<WorkspaceFolder[]>(`/api/v1/terminal/workspaces/${wsId}/folders`),
  createWsFolder: (wsId: string, data: { path: string }) =>
    userRequest<WorkspaceFolder>(`/api/v1/terminal/workspaces/${wsId}/folders`, { method: 'POST', body: JSON.stringify(data) }),
  deleteWsFolder: (folderId: string) => userRequest<void>(`/api/v1/terminal/folders/${folderId}`, { method: 'DELETE' }),
  deleteWsFolderPath: (wsId: string, path: string) =>
    userRequest<{ folders: number; files: number }>(
      `/api/v1/terminal/workspaces/${wsId}/folder-path?path=${encodeURIComponent(path)}`,
      { method: 'DELETE' },
    ),
  bulkDeleteWsItems: (wsId: string, data: { file_ids: string[]; folder_paths: string[] }) =>
    userRequest<{ deleted_files: number; deleted_folders: number }>(
      `/api/v1/terminal/workspaces/${wsId}/items/bulk-delete`,
      { method: 'POST', body: JSON.stringify(data) },
    ),

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
  updateSkill: (id: string, data: { name?: string; is_active?: boolean }) =>
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

// ── 平台扩展中心（仅 super_admin）────────────────────────────────────

export type PlatformExtensionKind = 'runtime_plugin' | 'system_tool' | 'library' | 'adapter_required' | 'incompatible';

export interface PlatformExtensionCatalogItem {
  id: string | null;
  slug: string;
  name: string;
  version: string;
  description: string;
  kind: PlatformExtensionKind;
  source: 'core' | 'official' | 'community' | 'reviewed' | 'external';
  status: string;
  removable: boolean;
  capabilities: string[];
  compatibility_warnings: string[];
  layer: string;
  operation: 'add' | 'replace';
  trust_level: string;
  runtime_requirements: Record<string, unknown>;
  compatibility_status: string;
  compatibility_reasons: string[];
  repository: string | null;
  homepage: string | null;
  package_name: string | null;
  available_versions: string[];
  category: string;
  metadata: Record<string, any>;
  lifecycle_status: string;
  installed: boolean;
  installed_version: string | null;
  active_source_id: string | null;
  latest_source_id: string | null;
}

export interface PlatformExtensionCatalogPage {
  items: PlatformExtensionCatalogItem[];
  page: number;
  page_size: number;
  total: number;
  counts: Record<'compatible' | 'adapter' | 'all' | 'installed', number>;
  sync: Record<string, any>;
}

export interface PlatformExtensionSource {
  id: string;
  source_type: string;
  locator: string;
  requested_version: string | null;
  resolved_version: string | null;
  commit_sha: string | null;
  artifact_ref: string | null;
  artifact_sha256: string | null;
  manifest: Record<string, any>;
  build_report: Record<string, any>;
  compatibility: Record<string, any>;
  status: string;
  review_status: string;
  error: string | null;
  imported_by_admin_id: number;
  approved_by_admin_id: number | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformExtensionRelease {
  id: string;
  version_no: number;
  name: string;
  manifest: Record<string, any>;
  checksum: string;
  status: string;
  is_active: boolean;
  base_release_id: string | null;
  created_by_admin_id: number;
  published_by_admin_id: number | null;
  activated_at: string | null;
  validation_report: Record<string, any>;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlatformExtensionEvent {
  id: number;
  source_id: string | null;
  release_id: string | null;
  actor_admin_id: number | null;
  event_type: string;
  status: string;
  details: Record<string, any>;
  created_at: string;
}

export interface PlatformSystemToolExecution {
  run_id: number;
  organization_id: string;
  task_id: string | null;
  user_id: string | null;
  exec_mode: string;
  run_status: string;
  tool_name: string;
  ok: boolean;
  result_preview: string;
  created_at: string;
}

export interface PlatformExtensionOverview {
  active_release: PlatformExtensionRelease | null;
  runtime_health: Record<string, any>;
  source_counts: Record<string, number>;
  release_counts: Record<string, number>;
  core_plugins: PlatformExtensionCatalogItem[];
  system_tools: PlatformExtensionCatalogItem[];
}

export interface StorageLifecycleOverview {
  pending_items: number;
  overdue_items: number;
  failed_items: number;
  reclaimable_bytes: number;
  runner_cache_bytes: number;
  runner_cache_limit_bytes: number;
}

export const storageLifecycle = {
  overview: () => request<StorageLifecycleOverview>('/api/v1/platform/storage-lifecycle/overview'),
  retry: () => request<Record<string, number>>('/api/v1/platform/storage-lifecycle/retry', { method: 'POST' }),
};

export const platformExtensions = {
  overview: () => request<PlatformExtensionOverview>('/api/v1/platform/extensions/overview'),
  catalog: (params: { q?: string; source?: string; layer?: string; compatibility?: string; offset?: number; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') qs.set(key, String(value)); });
    return request<PlatformExtensionCatalogItem[]>(`/api/v1/platform/extensions/catalog${qs.size ? `?${qs}` : ''}`);
  },
  catalogPage: (params: { q?: string; source?: string; layer?: string; state?: string; page?: number; page_size?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => { if (value !== undefined && value !== '') qs.set(key, String(value)); });
    return request<PlatformExtensionCatalogPage>(`/api/v1/platform/extensions/catalog/page${qs.size ? `?${qs}` : ''}`);
  },
  syncCatalog: () => request<Record<string, any>>('/api/v1/platform/extensions/catalog/sync', { method: 'POST' }),
  catalogDetail: (id: string) => request<PlatformExtensionCatalogItem>(`/api/v1/platform/extensions/catalog/${id}`),
  importCatalog: (id: string, data: { source?: 'npm' | 'github'; version?: string; ref?: string }) => request<PlatformExtensionSource>(
    `/api/v1/platform/extensions/catalog/${id}/import`, { method: 'POST', body: JSON.stringify(data) },
  ),
  adaptationBrief: (id: string) => requestText(`/api/v1/platform/extensions/catalog/${id}/adaptation-brief`, { method: 'POST' }),
  sources: () => request<PlatformExtensionSource[]>('/api/v1/platform/extensions/sources'),
  source: (id: string) => request<PlatformExtensionSource>(`/api/v1/platform/extensions/sources/${id}`),
  importNpm: (packageName: string, version: string) => request<PlatformExtensionSource>(
    '/api/v1/platform/extensions/import/npm',
    { method: 'POST', body: JSON.stringify({ package: packageName, version }) },
  ),
  importGithub: (repository: string, ref: string) => request<PlatformExtensionSource>(
    '/api/v1/platform/extensions/import/github',
    { method: 'POST', body: JSON.stringify({ repository, ref }) },
  ),
  importArchive: (archive: File) => {
    const data = new FormData();
    data.append('archive', archive);
    return request<PlatformExtensionSource>('/api/v1/platform/extensions/import/archive', { method: 'POST', body: data });
  },
  retrySource: (id: string) => request<PlatformExtensionSource>(
    `/api/v1/platform/extensions/sources/${id}/retry`, { method: 'POST' },
  ),
  approveSource: (id: string, approved: boolean, note?: string) => request<PlatformExtensionSource>(
    `/api/v1/platform/extensions/sources/${id}/approve`,
    { method: 'POST', body: JSON.stringify({ approved, note: note || null }) },
  ),
  sourceAdaptationPackage: (id: string) => requestText(
    `/api/v1/platform/extensions/sources/${id}/adaptation-package`,
  ),
  testSystemTool: (id: string, config: Record<string, unknown>, disabledOrganizationIds: string[] = []) =>
    request<PlatformExtensionRelease>(`/api/v1/platform/extensions/sources/${id}/test`, {
      method: 'POST', body: JSON.stringify({ config, disabled_organization_ids: disabledOrganizationIds }),
    }),
  installSystemTool: (id: string, config: Record<string, unknown>, disabledOrganizationIds: string[] = []) =>
    request<PlatformExtensionRelease>(`/api/v1/platform/extensions/sources/${id}/install`, {
      method: 'POST', body: JSON.stringify({ config, disabled_organization_ids: disabledOrganizationIds }),
    }),
  disableSystemTool: (id: string) => request<PlatformExtensionRelease>(
    `/api/v1/platform/extensions/sources/${id}/disable`, { method: 'POST' },
  ),
  rollbackSystemTool: (id: string) => request<PlatformExtensionRelease>(
    `/api/v1/platform/extensions/sources/${id}/rollback`, { method: 'POST' },
  ),
  systemToolExecutions: (id: string, limit = 100) => request<PlatformSystemToolExecution[]>(
    `/api/v1/platform/extensions/sources/${id}/executions?limit=${limit}`,
  ),
  releases: () => request<PlatformExtensionRelease[]>('/api/v1/platform/extensions/releases'),
  createRelease: (name: string, sourceIds: string[], config: Record<string, unknown> = {}) =>
    request<PlatformExtensionRelease>('/api/v1/platform/extensions/releases', {
      method: 'POST', body: JSON.stringify({ name, source_ids: sourceIds, config }),
    }),
  validateRelease: (id: string) => request<PlatformExtensionRelease>(
    `/api/v1/platform/extensions/releases/${id}/validate`, { method: 'POST' },
  ),
  publishRelease: (id: string) => request<PlatformExtensionRelease>(
    `/api/v1/platform/extensions/releases/${id}/publish`, { method: 'POST' },
  ),
  rollbackRelease: (id: string) => request<PlatformExtensionRelease>(
    `/api/v1/platform/extensions/releases/${id}/rollback`, { method: 'POST' },
  ),
  events: () => request<PlatformExtensionEvent[]>('/api/v1/platform/extensions/events'),
};
