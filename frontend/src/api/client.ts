/**
 * API 客户端 — 统一封装所有后端 HTTP 请求
 */
import { buildTaskRunFilePayload } from '../utils/workspaceFileLinks';
import {
  adminFetch,
  authorizeAdminXhr,
  getAdminAccessToken,
  handleAdminXhrUnauthorized,
} from '../auth/adminSession';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

function responseErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object') {
    const message = (detail as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return fallback;
}

function withWorkspaceVersion(path: string, versionId?: string | null): string {
  if (!versionId) return path;
  return `${path}${path.includes('?') ? '&' : '?'}version_id=${encodeURIComponent(versionId)}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const isMultipart = options?.body instanceof FormData;
  const headers: Record<string, string> = isMultipart ? {} : { 'Content-Type': 'application/json' };
  const { headers: optionHeaders, ...requestOptions } = options ?? {};

  const resp = await adminFetch(`${BASE_URL}${path}`, {
    ...requestOptions,
    headers: { ...headers, ...(optionHeaders as Record<string, string> | undefined) },
  });

  if (resp.status === 401) {
    if (window.location.pathname.startsWith('/f/')) {
      sessionStorage.setItem('zhuojian_return_to', `${window.location.pathname}${window.location.search}`);
    }
    throw new ApiError(401, '登录已失效，请重新登录');
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, responseErrorMessage(body, resp.statusText), body);
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
  /** 历史只读字段；后端不再执行或接受写入。 */
  readonly budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  budget_cap_credits: number | null;
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
  /** 历史只读字段；后端不再执行或接受写入。 */
  readonly budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  budget_cap_credits: number | null;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface LlmProvider {
  id: string;
  organization_id: string;
  name: string;
  vendor: 'openai' | 'anthropic' | 'azure_openai' | 'aliyun_bailian' | 'volcengine_ark' | 'custom';
  provider_type: string;
  region: string | null;
  workspace_id: string | null;
  scope_type: 'organization' | 'department';
  department_id: string | null;
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
  routing_priority: number;
  is_active: boolean;
  verification_status: 'unverified' | 'partially_verified' | 'verified' | 'failed' | 'legacy';
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
  routing_priority?: number;
  is_active?: boolean;
  config?: Record<string, unknown>;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  key_name: string;
  scope_type: 'organization' | 'department';
  organization_id: string;
  department_id: string | null;
  allowed_models: string[];
  rate_limit_rpm: number | null;
  rate_limit_tpm: number | null;
  /** 历史只读字段；后端不再执行或接受写入。 */
  readonly budget_cap_usd: string | null;
  budget_cap_tokens: number | null;
  budget_cap_credits: number | null;
  is_active: boolean;
  expires_at: string | null;
  last_used_at: string | null;
  created_at: string;
  revoked_at: string | null;
}

export interface ApiKeyWithSecret extends ApiKey {
  /** 创建响应中仅返回一次；后续接口无法恢复。 */
  key: string;
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
  scope_type: 'organization' | 'department';
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
      xhr.onload = () => {
        if (xhr.status === 401) {
          handleAdminXhrUnauthorized(xhr.status);
          reject(new ApiError(401, '登录已失效，请重新登录'));
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
      authorizeAdminXhr(xhr).then(() => xhr.send(fd)).catch(() => reject(new ApiError(0, '无法建立安全上传会话')));
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
  reorder: (orgId: string, departmentIds: string[]) =>
    request<Department[]>(`/api/v1/organizations/${orgId}/departments/reorder`, {
      method: 'PUT', body: JSON.stringify({ department_ids: departmentIds }),
    }),
  delete: (id: string) =>
    request<void>(`/api/v1/departments/${id}`, { method: 'DELETE' }),
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
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
}

async function requestBlob(path: string, tokenKey: string, signal?: AbortSignal): Promise<Blob> {
  const isAdminRequest = tokenKey === 'ai_infra_token';
  const token = isAdminRequest ? getAdminAccessToken() : sessionStorage.getItem(tokenKey);
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  const init: RequestInit = { headers, signal };
  const resp = isAdminRequest
    ? await adminFetch(`${BASE_URL}${path}`, init)
    : await fetch(`${BASE_URL}${path}`, init);
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, responseErrorMessage(body, resp.statusText), body);
  }
  return resp.blob();
}

export interface UserCreateInput {
  username: string;
  display_name?: string | null;
  role: string;
  role_ids?: string[];
  department_ids?: string[];
  department_id?: string | null;
  is_active?: boolean;
  password: string;
}

export interface EffectiveAccessSource {
  type: 'role' | 'membership' | 'organization' | 'ownership';
  id: string;
  name: string;
}

export interface WorkspaceCapabilities {
  read: boolean;
  create: boolean;
  update: boolean;
  delete: boolean;
  manage: boolean;
  publish: boolean;
}

/** 文件级最小能力集。旧服务未返回时由所属工作空间能力回退。 */
export interface WorkspaceFileCapabilities {
  read: boolean;
  create: boolean;
  update: boolean;
  delete: boolean;
}

export interface FileFormatCapability {
  format: string;
  mimeTypes: string[];
  family: 'spreadsheet' | 'document' | 'presentation' | 'pdf' | 'text' | 'image' | 'archive';
  capabilities: {
    create: boolean;
    inspect: boolean;
    edit: boolean;
    convert: boolean;
    preview: boolean;
  };
  nativeOrCompatibility: 'native' | 'compatibility';
  canonicalOutputFormat: string;
  conversionTargets: string[];
  limitations: string[];
}

export interface FileCapabilityRegistryResponse {
  formats: FileFormatCapability[];
  defaultOutputs: Record<string, string>;
}

export interface EffectiveWorkspaceAccess {
  id: string;
  name: string;
  slug: string;
  scope_type: 'organization' | 'department' | 'user';
  scope_id: string | null;
  capabilities: WorkspaceCapabilities;
  sources: Partial<Record<'read' | 'create' | 'update' | 'delete', EffectiveAccessSource[]>>;
}

export interface EffectiveAccess {
  roles: RoleSummary[];
  workspaces: EffectiveWorkspaceAccess[];
}

export const users = {
  list: (orgId: string) => request<User[]>(`/api/v1/organizations/${orgId}/users`),
  get: (id: string) => request<User>(`/api/v1/users/${id}`),
  effectiveAccess: (id: string) => request<EffectiveAccess>(`/api/v1/users/${id}/effective-access`),
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
  system_key: string | null;
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
  messageSpeechPlan: (taskId: string, messageId: string) => userRequest<{ content_version: string; segment_count: number }>(
    `/api/v1/multimodal/message-speech/plan?task_id=${encodeURIComponent(taskId)}&message_id=${encodeURIComponent(messageId)}`),
  readMessageSegment: (taskId: string, messageId: string, segmentIndex: number, contentVersion: string) =>
    userRequest<{ job_id: string }>('/api/v1/multimodal/message-speech', {
      method: 'POST', body: JSON.stringify({ task_id: taskId, message_id: messageId,
        segment_index: segmentIndex, expected_content_version: contentVersion }),
    }),
  readMessage: (taskId: string, messageId: string) => userRequest<{ job_id: string }>(
    '/api/v1/multimodal/message-speech', {
      method: 'POST', body: JSON.stringify({ task_id: taskId, message_id: messageId }),
    }),
  cancelMessageSpeech: (id: string) => userRequest<void>(
    `/api/v1/multimodal/message-speech/${id}`, { method: 'DELETE' }),
  createRecording: (data: { size_bytes: number; content_type: string; sha256: string; request_id: string }) =>
    userRequest<{ job_id: string; url: string; fallback_url?: string; headers: Record<string, string> }>(
      '/api/v1/multimodal/recordings', { method: 'POST', body: JSON.stringify(data) }),
  completeRecording: (id: string) => userRequest<{ job_id: string }>(
    `/api/v1/multimodal/recordings/${id}/complete`, { method: 'POST' }),
  cancelRecording: (id: string) => userRequest<void>(
    `/api/v1/multimodal/recordings/${id}`, { method: 'DELETE' }),
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

// ── AI quota usage (credits + token consumption) ─────────────────────

export type BudgetScopeType = 'organization' | 'department' | 'api_key';

export interface BudgetScopeCaps {
  rpm: number | null;
  tpm: number | null;
  monthly_tokens: number | null;
  monthly_credits: number | null;
}

export interface BudgetScopeUsageValues {
  actual_tokens: number;
  held_unknown_tokens: number;
  credits: number;
  requests: number;
}

export interface BudgetScopeRemaining {
  monthly_tokens: number | null;
  monthly_credits: number | null;
}

export interface BudgetScopeUsage {
  scope_type: BudgetScopeType;
  scope_id: string;
  scope_name: string;
  parent_scope_type: BudgetScopeType | null;
  parent_scope_id: string | null;
  is_inactive: boolean;
  direct_caps: BudgetScopeCaps;
  usage: BudgetScopeUsageValues;
  direct_remaining: BudgetScopeRemaining;
  effective_remaining: BudgetScopeRemaining;
}

export interface BudgetProviderUsage {
  provider_id: string | null;
  provider_name: string;
  provider_type: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  retained_unknown_tokens: number;
  credits: number;
  request_count: number;
}

export interface BudgetKeyUsage {
  api_key_id: string | null;
  key_name: string;
  key_prefix: string | null;
  budget_cap_tokens: number | null;
  budget_cap_credits: number | null;
  is_revoked: boolean;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  retained_unknown_tokens: number;
  credits: number;
  request_count: number;
  effective_remaining: BudgetScopeRemaining | null;
  providers: BudgetProviderUsage[];
}

export interface BudgetUsageResponse {
  timezone: string;
  as_of: string;
  period_start: string;
  period_end: string;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  retained_unknown_tokens: number;
  credits: number;
  request_count: number;
  enforcement: {
    rpm: string;
    tpm: string;
    token_budget: string;
    credit_budget: string;
    usd_budget: 'legacy_read_only_not_enforced' | string;
    durable_ledger: string;
  };
  scopes: BudgetScopeUsage[];
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
  capabilities?: WorkspaceCapabilities;
}

export interface WorkspaceFile {
  id: string; workspace_id: string; path: string; size: number;
  content_hash: string | null; content: string | null; metadata: Record<string, unknown>;
  extracted_text: string | null; parse_status: 'unparsed' | 'queued' | 'processing' | 'ready' | 'unsupported' | 'failed';
  parse_kind: string | null; parse_error: string | null;
  created_at: string; updated_at: string;
  presentation?: WorkspaceFilePresentation;
  workspace_name?: string; workspace_slug?: string; canonical_path?: string;
  current_version_id?: string | null; previous_version_id?: string | null; current_version_no?: number | null;
  resolved_version_id?: string | null; resolved_version_no?: number | null; is_historical?: boolean;
  capabilities?: WorkspaceFileCapabilities; effective_capabilities?: WorkspaceFileCapabilities; internal_url?: string;
}

export interface WorkspaceFilePresentation {
  display_name: string; source_kind: string; source_task_id: string | null;
  source_task_title: string | null; created_at: string | null;
}

export interface WorkspaceFileListItem {
  id: string; workspace_id: string; path: string; original_filename: string; size: number;
  mime_type: string | null; is_binary: boolean; content_hash: string | null;
  parse_status: 'unparsed' | 'queued' | 'processing' | 'ready' | 'unsupported' | 'failed';
  parse_kind: string | null; parse_error: string | null;
  created_at: string; updated_at: string;
  presentation: WorkspaceFilePresentation;
  workspace_name?: string; workspace_slug?: string; canonical_path?: string;
  current_version_id?: string | null; current_version_no?: number | null;
  capabilities?: WorkspaceFileCapabilities; effective_capabilities?: WorkspaceFileCapabilities; internal_url?: string;
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

export interface WorkspacePreviewSession {
  mode: 'weboffice' | 'pdfjs' | 'browser_office' | 'text' | 'spreadsheet_preview' | 'native' | 'blob' | 'fallback' | 'download_only';
  filename: string;
  mime_type: string;
  size: number;
  url: string | null;
  fallback_url: string | null;
  headers: Record<string, string>;
  weboffice_url: string | null;
  access_token: string | null;
  refresh_token: string | null;
  access_token_expired_time: string | null;
  refresh_token_expired_time: string | null;
  refresh_context: string | null;
  reason: string | null;
  strict_range: boolean;
  file_id?: string | null;
  source_version_id?: string | null;
}

export interface WorkspaceFallbackPreview {
  status: 'missing' | 'queued' | 'processing' | 'ready' | 'failed';
  attempt_count: number;
  url: string | null;
  fallback_url: string | null;
  expires_at: string | null;
  error: string | null;
}

export type WorkspacePreviewPreferredMode = 'default' | 'fast_layout' | 'interactive_ppt';

export interface WorkspaceSpreadsheetPreview {
  status: 'missing' | 'queued' | 'processing' | 'ready' | 'failed';
  attempt_count: number;
  sheets: Array<{ name: string; rows: number; columns: number; pages: number; truncated: boolean }>;
  error: string | null;
}

export interface WorkspaceSpreadsheetPage {
  sheet: string; page: number; page_size: number; total_rows: number; truncated: boolean;
  rows: Array<Array<string | number | boolean | null>>;
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
  /** Present only after the user explicitly confirms replacing this logical file. */
  targetFileId?: string;
  baseVersionId?: string;
  idempotencyKey?: string;
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
    Object.entries(uploadMutationPayload(options)).forEach(([key, value]) => fd.append(key, value || ''));
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE_URL}${url}`);
    const isAdminRequest = tokenKey === 'ai_infra_token';
    const token = isAdminRequest ? getAdminAccessToken() : sessionStorage.getItem(tokenKey);
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        options?.onProgress?.(Math.min(100, Math.round((event.loaded / event.total) * 100)));
      }
    };
    xhr.upload.onload = () => options?.onUploadComplete?.();
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        let body: unknown = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* keep statusText */ }
        reject(new ApiError(xhr.status, responseErrorMessage(body, xhr.statusText), body));
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
    if (isAdminRequest) {
      authorizeAdminXhr(xhr).then(() => xhr.send(fd)).catch(() => reject(new ApiError(0, '无法建立安全上传会话')));
    } else {
      xhr.send(fd);
    }
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
  node_type: 'organization' | 'department' | 'user';
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
  getFileOriginalPreviewSource: (id: string, versionId?: string) =>
    request<WorkspaceOriginalPreviewSource>(withWorkspaceVersion(`/api/v1/files/${id}/original-preview-source`, versionId)),
  createFilePreviewSession: (id: string, clientOpenId: string, preferredMode: WorkspacePreviewPreferredMode = 'default', versionId?: string) =>
    request<WorkspacePreviewSession>(`/api/v1/files/${id}/preview-session`, {
      method: 'POST', body: JSON.stringify({ client_open_id: clientOpenId, preferred_mode: preferredMode, version_id: versionId }),
    }),
  refreshFilePreviewSession: (id: string, accessToken: string, refreshToken: string, refreshContext: string) =>
    request<WorkspacePreviewSession>(`/api/v1/files/${id}/preview-session/refresh`, {
      method: 'POST', body: JSON.stringify({ access_token: accessToken, refresh_token: refreshToken, refresh_context: refreshContext }),
    }),
  startFileFallbackPreview: (id: string, versionId?: string) =>
    request<WorkspaceFallbackPreview>(withWorkspaceVersion(`/api/v1/files/${id}/fallback-preview`, versionId), { method: 'POST' }),
  getFileFallbackPreview: (id: string, versionId?: string) =>
    request<WorkspaceFallbackPreview>(withWorkspaceVersion(`/api/v1/files/${id}/fallback-preview`, versionId)),
  startFileSpreadsheetPreview: (id: string, versionId?: string) =>
    request<WorkspaceSpreadsheetPreview>(withWorkspaceVersion(`/api/v1/files/${id}/spreadsheet-preview`, versionId), { method: 'POST' }),
  getFileSpreadsheetPreview: (id: string, versionId?: string) =>
    request<WorkspaceSpreadsheetPreview>(withWorkspaceVersion(`/api/v1/files/${id}/spreadsheet-preview`, versionId)),
  getFileSpreadsheetPage: (id: string, sheet: string, page: number, versionId?: string) =>
    request<WorkspaceSpreadsheetPage>(withWorkspaceVersion(`/api/v1/files/${id}/spreadsheet-preview/sheets/${encodeURIComponent(sheet)}/pages/${page}`, versionId)),
  getFileDownloadTicket: (id: string, versionId?: string) =>
    request<WorkspaceDownloadTicket>(withWorkspaceVersion(`/api/v1/files/${id}/download-ticket`, versionId), { method: 'POST' }),
  getFilePdfPreviewInfo: (id: string, versionId?: string) =>
    request<WorkspacePdfPreviewInfo>(withWorkspaceVersion(`/api/v1/files/${id}/pdf-preview/info`, versionId)),
  getFilePdfPreviewPage: (id: string, pageNumber: number, versionId?: string) =>
    requestBlob(withWorkspaceVersion(`/api/v1/files/${id}/pdf-preview/pages/${pageNumber}`, versionId), 'ai_infra_token'),
  getFileOriginalPreview: (id: string, versionId?: string) => requestBlob(withWorkspaceVersion(`/api/v1/files/${id}/original-preview`, versionId), 'ai_infra_token'),
  downloadFile: (id: string, versionId?: string) => requestBlob(withWorkspaceVersion(`/api/v1/files/${id}/download`, versionId), 'ai_infra_token'),
  reparseFile: (id: string) => request<WorkspaceFile>(`/api/v1/files/${id}/reparse`, { method: 'POST' }),
  updateFile: (id: string, data: {
    content?: string; metadata?: Record<string, unknown>;
    base_version_id?: string | null; idempotency_key?: string;
  }) =>
    request<WorkspaceFile>(`/api/v1/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteFile: (id: string, data: { base_version_id: string; idempotency_key: string }) =>
    request<void>(`/api/v1/files/${id}`, {
      method: 'DELETE', body: JSON.stringify(data),
    }),
  listFileVersions: (id: string) => request<WorkspaceFileVersion[]>(`/api/v1/files/${id}/versions`),
  getFileVersion: (id: string, versionId: string) =>
    request<WorkspaceFile>(`/api/v1/files/${id}/versions/${versionId}`),
  restoreFileVersion: (id: string, versionId: string, options: { base_version_id: string; idempotency_key: string }) =>
    request<WorkspaceFile>(`/api/v1/files/${id}/versions/${versionId}/restore`, {
      method: 'POST', body: JSON.stringify(options),
    }),
  listFolders: (wsId: string) => request<WorkspaceFolder[]>(`/api/v1/workspaces/${wsId}/folders`),
  createFolder: (wsId: string, data: { path: string }) =>
    request<WorkspaceFolder>(`/api/v1/workspaces/${wsId}/folders`, { method: 'POST', body: JSON.stringify(data) }),
  deleteFolder: (id: string) => request<void>(`/api/v1/folders/${id}`, { method: 'DELETE' }),
  deleteFolderPath: (wsId: string, path: string) =>
    request<{ folders: number; files: number }>(`/api/v1/workspaces/${wsId}/folder-path?path=${encodeURIComponent(path)}`, { method: 'DELETE' }),
  bulkDeleteItems: (wsId: string, data: { file_ids: string[]; folder_paths: string[] }) =>
    request<{ deleted_files: number; deleted_folders: number }>(`/api/v1/workspaces/${wsId}/items/bulk-delete`, { method: 'POST', body: JSON.stringify(data) }),
  listTrash: (wsId: string) => request<WorkspaceFile[]>(`/api/v1/workspaces/${wsId}/trash`),
  restoreTrash: (wsId: string, fileId: string, options: { base_version_id: string; idempotency_key: string }) =>
    request<WorkspaceFile>(`/api/v1/workspaces/${wsId}/trash/${fileId}/restore`, {
      method: 'POST', body: JSON.stringify(options),
    }),
  listAudit: (wsId: string, limit = 200) =>
    request<WorkspaceAuditEvent[]>(`/api/v1/workspaces/${wsId}/audit?limit=${limit}`),
};

// ── Agent Platform: Agents ─────────────────────────────────────────────

export interface Agent {
  id: string; organization_id: string; scope_type: string; scope_id: string | null; created_by: string | null;
  name: string; slug: string; description: string | null;
  system_prompt: string;
  is_active: boolean; version: number; created_at: string; updated_at: string;
}

/** 跨全部可访问工作空间的文件轻量摘要，供个人助手引用文件。 */
export interface WorkspaceFileSummary {
  id: string; workspace_id: string; workspace_name: string;
  path: string; original_filename: string; presentation: WorkspaceFilePresentation;
  scope_type: string; is_binary: boolean;
  workspace_slug?: string; canonical_path?: string;
  current_version_id?: string | null; current_version_no?: number | null;
  capabilities?: WorkspaceFileCapabilities; effective_capabilities?: WorkspaceFileCapabilities; internal_url?: string;
}

export interface WorkspaceFileRefV1 {
  file_id: string;
  scope: 'turn' | 'task';
  version_id?: string;
  follow_latest?: boolean;
}

export interface WorkspaceFileEvent {
  id: number;
  file_id: string;
  version_id: string | null;
  event_type: string;
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

export interface ScopeRef { scope_type: string; scope_id: string | null }

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
    memory: { load_runs: number; facts_loaded: number; extract_runs: number; facts_saved: number };
  };
}

export interface ToolMetrics {
  calls: number; success_count: number; error_count: number; error_rate: number; avg_latency_ms: number;
  by_action: {
    action_id: string; action_key: string; action_name: string; module_key: string | null;
    operation: string | null; calls: number; error_count: number; error_rate: number; avg_latency_ms: number;
  }[];
  inventory: Record<string, never>;
}

export interface OverviewMetrics { router: RouterMetrics; agent: AgentMetrics; tool: ToolMetrics; }

export const monitor = {
  overview: (orgId: string) => request<OverviewMetrics>(`/api/v1/organizations/${orgId}/monitor/overview`),
  router: (orgId: string) => request<RouterMetrics>(`/api/v1/organizations/${orgId}/monitor/router`),
  agents: (orgId: string) => request<AgentMetrics>(`/api/v1/organizations/${orgId}/monitor/agents`),
  tools: (orgId: string) => request<ToolMetrics>(`/api/v1/organizations/${orgId}/monitor/tools`),
};

// ── Terminal User Portal (user JWT) ────────────────────────────────────
// 终端用户 bearer 只保留在当前标签会话，不在浏览器持久化长期凭据。

const USER_TOKEN_KEY = 'ai_infra_user_token';

function userRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const token = sessionStorage.getItem(USER_TOKEN_KEY);
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
        const stored = localStorage.getItem('ai_infra_user');
        if (window.location.pathname.startsWith('/f/')) {
          sessionStorage.setItem('zhuojian_return_to', `${window.location.pathname}${window.location.search}`);
        }
        sessionStorage.removeItem(USER_TOKEN_KEY);
        localStorage.removeItem('ai_infra_user');
        // 回跳到当前 slug 的用户登录页（或平台 /login 兜底）
        const m = window.location.pathname.match(/^\/([^/]+)\/terminal/);
        let storedSlug: string | null = null;
        try { storedSlug = stored ? JSON.parse(stored)?.organization_slug ?? null : null; } catch { storedSlug = null; }
        const slug = m ? m[1] : storedSlug;
        window.location.href = slug ? `/${slug}/terminal/login` : '/login';
        throw new ApiError(401, '登录已失效，请重新登录');
      }
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new ApiError(resp.status, responseErrorMessage(body, resp.statusText), body);
      }
      if (resp.status === 204) return undefined as T;
      return resp.json();
    });
}

export interface TerminalUser {
  user: User;
  department_ids: string[];
  department_id: string | null;
  scopes: [string, string | null][];
}

export interface TerminalResources {
  workspaces: Workspace[];
  audio_capabilities?: Partial<Record<'speech_to_text' | 'text_to_speech', {
    available: boolean; code: string; messageZh: string;
  }>>;
  /** 用户默认装配：默认工作空间（个人）+ 默认模型（最近一次使用）。 */
  defaults?: { workspace_id: string | null; model_alias: string | null };
}

export interface TerminalModels {
  /** 用户可用的对话模型名（按可访问 API Key 与有效部署聚合）。 */
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

// Keep the SaaS API out of the file data path. Every non-empty browser upload
// goes directly to OSS after the API has authorised and signed the request.
// The legacy proxy is retained only for zero-byte files, which OSS direct
// upload sessions intentionally reject.
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

interface ResumableUploadRecord {
  key: string;
  session_id: string;
  method: 'MULTIPART';
  part_size: number;
  expected_parts: number;
  expires_at: string;
  completed_parts: MultipartUploadPart[];
  updated_at: number;
}

const OSS_MAX_ACTIVE_REQUESTS = 4;
const UPLOAD_RESUME_DB = 'zhuojian-workspace-uploads';
const UPLOAD_RESUME_STORE = 'sessions';
let activeOssRequests = 0;
const ossRequestWaiters: Array<() => void> = [];

function uploadMutationPayload(options?: WorkspaceUploadOptions) {
  const values = [options?.targetFileId, options?.baseVersionId, options?.idempotencyKey];
  if (values.every(Boolean)) {
    return {
      target_file_id: options!.targetFileId,
      base_version_id: options!.baseVersionId,
      idempotency_key: options!.idempotencyKey,
    };
  }
  if (values.some(Boolean)) throw new ApiError(400, '作为新版本上传时缺少文件版本信息，请刷新后重试');
  return {};
}

function uploadResumeKey(
  kind: 'admin' | 'user', wsId: string, path: string, file: File, options?: WorkspaceUploadOptions,
) {
  return [
    kind, wsId, path, file.name, file.size, file.lastModified,
    options?.targetFileId || '', options?.baseVersionId || '',
  ].map(encodeURIComponent).join('|');
}

function openUploadResumeDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(UPLOAD_RESUME_DB, 1);
    request.onupgradeneeded = () => {
      if (!request.result.objectStoreNames.contains(UPLOAD_RESUME_STORE)) {
        request.result.createObjectStore(UPLOAD_RESUME_STORE, { keyPath: 'key' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function readUploadResume(key: string): Promise<ResumableUploadRecord | null> {
  try {
    const db = await openUploadResumeDb();
    return await new Promise<ResumableUploadRecord | null>((resolve, reject) => {
      const request = db.transaction(UPLOAD_RESUME_STORE, 'readonly').objectStore(UPLOAD_RESUME_STORE).get(key);
      request.onsuccess = () => resolve((request.result as ResumableUploadRecord | undefined) ?? null);
      request.onerror = () => reject(request.error);
    }).finally(() => db.close());
  } catch {
    return null;
  }
}

async function writeUploadResume(record: ResumableUploadRecord): Promise<void> {
  try {
    const db = await openUploadResumeDb();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(UPLOAD_RESUME_STORE, 'readwrite');
      transaction.objectStore(UPLOAD_RESUME_STORE).put(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    db.close();
  } catch { /* IndexedDB is an optional recovery aid. */ }
}

async function deleteUploadResume(key: string): Promise<void> {
  try {
    const db = await openUploadResumeDb();
    await new Promise<void>((resolve, reject) => {
      const transaction = db.transaction(UPLOAD_RESUME_STORE, 'readwrite');
      transaction.objectStore(UPLOAD_RESUME_STORE).delete(key);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(transaction.error);
    });
    db.close();
  } catch { /* Session expiry remains the server-side cleanup fallback. */ }
}

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
): Promise<string> {
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
        resolve(xhr.getResponseHeader('ETag') || 'uploaded');
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
  initialParts: MultipartUploadPart[],
  onPartComplete: (part: MultipartUploadPart) => Promise<void>,
  options?: WorkspaceUploadOptions,
): Promise<MultipartPartReceipt[]> {
  const partSize = session.part_size || 0;
  const expectedParts = session.expected_parts || Math.ceil(file.size / Math.max(partSize, 1));
  if (partSize <= 0 || expectedParts <= 0) throw new ApiError(500, '对象存储分片参数无效');

  const controller = new AbortController();
  const abortFromCaller = () => controller.abort();
  options?.signal?.addEventListener('abort', abortFromCaller, { once: true });
  if (options?.signal?.aborted) controller.abort();

  const uploadedBytes = new Map<number, number>(
    initialParts.map((part) => [part.part_number, part.size]),
  );
  const alreadyUploaded = new Set(initialParts.map((part) => part.part_number));
  const reportProgress = () => {
    const loaded = Array.from(uploadedBytes.values()).reduce((sum, bytes) => sum + bytes, 0);
    options?.onProgress?.(Math.min(99, Math.round((loaded / file.size) * 100)));
  };
  let nextPart = 1;
  const uploadOne = async (partNumber: number) => {
    if (alreadyUploaded.has(partNumber)) return;
    const start = (partNumber - 1) * partSize;
    const chunk = file.slice(start, Math.min(start + partSize, file.size));
    let lastError: unknown;
    let timeoutCount = 0;
    let useFallback = false;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try {
        const signed = await signPart(partNumber);
        const target = useFallback && signed.fallback_url ? signed.fallback_url : signed.url;
        const etag = await putMultipartPartAttempt(signed, target, chunk, controller.signal, (loaded) => {
          uploadedBytes.set(partNumber, loaded);
          reportProgress();
        });
        await onPartComplete({ part_number: partNumber, etag, size: chunk.size });
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
    reportProgress();
    await Promise.all(Array.from({ length: Math.min(2, expectedParts) }, () => worker()));
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
  if (file.size === 0) {
    return uploadWorkspaceFile(
      `/api/v1/terminal/workspaces/${wsId}/files/upload`, file, path, USER_TOKEN_KEY, options,
    );
  }
  const initiate = (weakNetwork: boolean) => userRequest<DirectUploadSession>(
    `/api/v1/terminal/workspaces/${wsId}/uploads/initiate`, { method: 'POST', body: JSON.stringify({
      path, filename: file.name, content_type: file.type || 'application/octet-stream',
      size: file.size, weak_network: weakNetwork, ...uploadMutationPayload(options),
    }) },
  );
  const resumeKey = uploadResumeKey('user', wsId, path, file, options);
  let record = await readUploadResume(resumeKey);
  let session: DirectUploadSession | null = null;
  let initialParts: MultipartUploadPart[] = [];
  if (record && Date.parse(record.expires_at) > Date.now()) {
    try {
      const status = await userRequest<MultipartUploadStatus>(`/api/v1/terminal/uploads/${record.session_id}`);
      if (status.status === 'pending' && status.part_size === record.part_size && status.expected_parts === record.expected_parts) {
        session = {
          id: record.session_id, method: 'MULTIPART', url: null, fallback_url: null, headers: {},
          expires_at: record.expires_at, max_file_bytes: WORKSPACE_MAX_FILE_BYTES,
          part_size: record.part_size, expected_parts: record.expected_parts,
        };
        initialParts = status.uploaded_parts;
      }
    } catch { /* Expired or revoked sessions are replaced below. */ }
  }
  if (!session) {
    await deleteUploadResume(resumeKey);
    session = await initiate(weakNetworkPreferred());
    if (session.method === 'MULTIPART') {
      record = {
        key: resumeKey, session_id: session.id, method: 'MULTIPART',
        part_size: session.part_size || 0, expected_parts: session.expected_parts || 0,
        expires_at: session.expires_at, completed_parts: [], updated_at: Date.now(),
      };
      await writeUploadResume(record);
    }
  }
  try {
    if (session.method === 'MULTIPART') {
      const parts = await uploadMultipartWorkspaceFile(
        session,
        file,
        (partNumber) => userRequest<MultipartPartSigned>(
          `/api/v1/terminal/uploads/${session.id}/parts/${partNumber}/sign`, { method: 'POST' },
        ),
        () => userRequest<MultipartUploadStatus>(`/api/v1/terminal/uploads/${session.id}`),
        initialParts,
        async (part) => {
          if (!record) return;
          record.completed_parts = [...record.completed_parts.filter((item) => item.part_number !== part.part_number), part];
          record.updated_at = Date.now();
          await writeUploadResume(record);
        },
        options,
      );
      const result = await userRequest<WorkspaceFile>(`/api/v1/terminal/uploads/${session.id}/complete`, {
        method: 'POST', body: JSON.stringify({ parts }),
      });
      await deleteUploadResume(resumeKey);
      return result;
    }
    const etag = await putSignedWorkspaceFile(session, file, options);
    return await userRequest<WorkspaceFile>(`/api/v1/terminal/uploads/${session.id}/complete`, {
      method: 'POST', body: JSON.stringify({ etag }),
    });
  } catch (error) {
    throw error;
  }
}

async function uploadAdminWorkspaceFile(
  wsId: string, file: File, path: string, options?: WorkspaceUploadOptions,
): Promise<WorkspaceFile> {
  if (file.size > WORKSPACE_MAX_FILE_BYTES) throw new ApiError(413, '文件超过 5GB 存储上限');
  if (file.size === 0) {
    return uploadWorkspaceFile(
      `/api/v1/workspaces/${wsId}/files/upload`, file, path, 'ai_infra_token', options,
    );
  }
  const initiate = (weakNetwork: boolean) => request<DirectUploadSession>(`/api/v1/workspaces/${wsId}/uploads/initiate`, {
    method: 'POST', body: JSON.stringify({
      path, filename: file.name, content_type: file.type || 'application/octet-stream',
      size: file.size, weak_network: weakNetwork, ...uploadMutationPayload(options),
    }),
  });
  const resumeKey = uploadResumeKey('admin', wsId, path, file, options);
  let record = await readUploadResume(resumeKey);
  let session: DirectUploadSession | null = null;
  let initialParts: MultipartUploadPart[] = [];
  if (record && Date.parse(record.expires_at) > Date.now()) {
    try {
      const status = await request<MultipartUploadStatus>(`/api/v1/workspace-uploads/${record.session_id}`);
      if (status.status === 'pending' && status.part_size === record.part_size && status.expected_parts === record.expected_parts) {
        session = {
          id: record.session_id, method: 'MULTIPART', url: null, fallback_url: null, headers: {},
          expires_at: record.expires_at, max_file_bytes: WORKSPACE_MAX_FILE_BYTES,
          part_size: record.part_size, expected_parts: record.expected_parts,
        };
        initialParts = status.uploaded_parts;
      }
    } catch { /* Expired or revoked sessions are replaced below. */ }
  }
  if (!session) {
    await deleteUploadResume(resumeKey);
    session = await initiate(weakNetworkPreferred());
    if (session.method === 'MULTIPART') {
      record = {
        key: resumeKey, session_id: session.id, method: 'MULTIPART',
        part_size: session.part_size || 0, expected_parts: session.expected_parts || 0,
        expires_at: session.expires_at, completed_parts: [], updated_at: Date.now(),
      };
      await writeUploadResume(record);
    }
  }
  try {
    if (session.method === 'MULTIPART') {
      const parts = await uploadMultipartWorkspaceFile(
        session,
        file,
        (partNumber) => request<MultipartPartSigned>(
          `/api/v1/workspace-uploads/${session.id}/parts/${partNumber}/sign`, { method: 'POST' },
        ),
        () => request<MultipartUploadStatus>(`/api/v1/workspace-uploads/${session.id}`),
        initialParts,
        async (part) => {
          if (!record) return;
          record.completed_parts = [...record.completed_parts.filter((item) => item.part_number !== part.part_number), part];
          record.updated_at = Date.now();
          await writeUploadResume(record);
        },
        options,
      );
      const result = await request<WorkspaceFile>(`/api/v1/workspace-uploads/${session.id}/complete`, {
        method: 'POST', body: JSON.stringify({ parts }),
      });
      await deleteUploadResume(resumeKey);
      return result;
    }
    const etag = await putSignedWorkspaceFile(session, file, options);
    return await request<WorkspaceFile>(`/api/v1/workspace-uploads/${session.id}/complete`, {
      method: 'POST', body: JSON.stringify({ etag }),
    });
  } catch (error) {
    throw error;
  }
}

export interface TaskConfig {
  workspace_id: string | null;
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
export type EnterpriseApplicationScope = 'organization' | 'role' | 'department' | 'user';
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
  managed_key: string | null;
  denied_resources: Record<string, unknown>;
  created_at: string; updated_at: string;
}

export interface EnterpriseApplication {
  id: string; organization_id: string; name: string; slug: string;
  description: string | null; icon_url: string | null; entry_url: string;
  display_mode: 'embedded' | 'external'; sort_order: number; is_active: boolean;
  admin_disabled: boolean;
  assistant_enabled: boolean; assistant_prompt: string | null;
  assistant_config: Record<string, unknown>; health_status: string;
  grants: EnterpriseApplicationGrant[];
  created_at: string; updated_at: string;
}

export type EnterpriseApplicationInput = Pick<EnterpriseApplication,
  'name' | 'slug' | 'entry_url' | 'display_mode' | 'sort_order' | 'is_active' | 'assistant_enabled'
> & Partial<Pick<EnterpriseApplication, 'description' | 'icon_url' | 'assistant_prompt' | 'assistant_config'>>;

export interface TerminalEnterpriseApplication {
  id: string; name: string; slug: string; description: string | null;
  icon_url: string | null; display_mode: 'embedded' | 'external';
  is_active?: boolean;
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
  page_keys: string[];
  /** v2 native launch isolation. Embedded launches fail closed when absent. */
  launch_nonce: string | null;
  allowed_origin: string | null;
  application_slug: string | null;
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
  platformAiCapability?: {
    type: 'vision.ocr' | 'vision.compare' | 'vision.classify' | 'speech.transcribe' | 'text.extract' | 'business.predict';
    inputKinds: Array<'image' | 'audio' | 'text' | 'json'>;
    humanConfirmation: 'required';
  };
}

export interface SubsystemAiRun {
  run_id: string;
  request_id: string;
  capability: 'vision.ocr' | 'vision.compare' | 'vision.classify' | 'speech.transcribe' | 'text.extract' | 'business.predict';
  application_id: string;
  module_key: string;
  page_key: string;
  action_key: string;
  status: 'queued' | 'processing' | 'succeeded' | 'failed' | 'cancelled';
  result: Record<string, unknown>;
  error: { code: string; messageZh: string; retryable: boolean } | null;
  created_at: string;
  updated_at: string;
  finished_at: string | null;
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
  credential_version: number;
  manifest_token_configured: boolean;
  sso_exchange_configured: boolean;
  action_signing_configured: boolean;
  event_signing_configured: boolean;
  credentials_complete: boolean;
  manifest_review_status: 'approved' | 'pending' | 'rejected';
  manifest_diff: Array<{
    securitySensitive?: boolean;
    changedPaths?: string[];
    changedPathCount?: number;
    changedPathsTruncated?: boolean;
    beforeDigest?: string;
    afterDigest?: string;
    [key: string]: unknown;
  }>;
  pending_contract_revision: string | null;
  pending_manifest: Record<string, unknown> | null;
  pending_manifest_digest: string | null;
}

export interface EnterpriseApplicationIntegrationInput {
  manifest_url: string;
  auth_token?: string;
  manifest_access_token?: string;
  sso_exchange_token?: string;
  action_signing_secret?: string;
  event_signing_secret?: string;
  clear_auth_token?: boolean;
  clear_sso_exchange_token?: boolean;
  clear_action_signing_secret?: boolean;
  clear_event_signing_secret?: boolean;
  sync_enabled: boolean;
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
  is_active: boolean; admin_disabled: boolean; created_at: string; updated_at: string;
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
  test: (id: string) => request<{ status: 'healthy' | 'unhealthy'; status_code: number | null; detail: string | null }>(
    `/api/v1/applications/${id}/test`, { method: 'POST' },
  ),
  integration: (id: string) => request<EnterpriseApplicationIntegration>(`/api/v1/applications/${id}/integration`),
  configureIntegration: (id: string, data: EnterpriseApplicationIntegrationInput) => request<EnterpriseApplicationIntegration>(`/api/v1/applications/${id}/integration`, {
    method: 'PUT', body: JSON.stringify(data),
  }),
  reviewManifest: (id: string, decision: 'approve' | 'reject', expectedManifestDigest: string) =>
    request<EnterpriseApplicationIntegration>(`/api/v1/applications/${id}/integration/manifest-review`, {
      method: 'POST', body: JSON.stringify({ decision, expected_manifest_digest: expectedManifestDigest }),
    }),
  syncIntegration: (id: string) => request<{
    status: 'healthy' | 'pending_review' | 'error'; manifest_updated: boolean; received_events: number;
    queued_deliveries: number; delivered_events: number; cursor_sequence: number; detail: string | null;
  }>(`/api/v1/applications/${id}/integration/sync`, { method: 'POST' }),
  actions: (id: string) => request<EnterpriseApplicationAction[]>(`/api/v1/applications/${id}/actions`),
  updateAction: (id: string, actionKey: string, isActive: boolean) =>
    request<EnterpriseApplicationAction>(
      `/api/v1/applications/${id}/actions/${encodeURIComponent(actionKey)}`,
      { method: 'PATCH', body: JSON.stringify({ is_active: isActive }) },
    ),
  eventRoutes: (id: string) => request<EnterpriseApplicationEventRoute[]>(`/api/v1/applications/${id}/event-routes`),
  replaceEventRoutes: (id: string, routes: Array<Omit<EnterpriseApplicationEventRoute, 'id' | 'application_id' | 'created_at' | 'updated_at'>>) =>
    request<EnterpriseApplicationEventRoute[]>(`/api/v1/applications/${id}/event-routes`, {
      method: 'PUT', body: JSON.stringify({ routes }),
    }),
};

export interface TerminalAgent {
  id: string; name: string; slug: string;
  scope_type: string; scope_id: string | null;
  description: string | null;
}

export interface ScopeNode {
  scope_type: 'organization' | 'department' | 'user';
  scope_id: string | null;
  name: string;
}

export interface TerminalTask {
  id: string;
  organization_id: string;
  user_id: string;
  department_id: string | null;
  session_id: string;
  title: string;
  message: string;
  config: TaskConfig;
  status: string;
  created_at: string;
  updated_at: string;
  match_excerpt?: string | null;
  last_page_context?: Record<string, unknown>;
  artifact_count?: number;
  run_status?: string | null;
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
    status: 'verified' | 'recovered' | 'partial' | 'failed' | 'legacy_unverified';
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

/** 高风险工具用户审批（SSE `approval_request` / `approval_decided` 与 POST .../approvals/{id} 共用）。 */
export type TerminalApprovalDecision = 'allow' | 'reject';
export type TerminalApprovalOutcome = 'allowed-once' | 'rejected' | 'cancelled' | 'unavailable';
export type TerminalApprovalDecidedBy = 'user' | 'timeout' | 'system';

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
  // 不能复用管理员 request 的 401 自动跳转，否则会跳到管理员登录页。
  // 这里走裸 fetch，401 当普通错误抛出，由登录页 message.error 提示并留在原 slug 终端登录页。
  loginBySlug: async (slug: string, username: string, password: string) => {
    const resp = await fetch(`${BASE_URL}/api/v1/users/login-by-slug`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slug, username, password }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new ApiError(resp.status, responseErrorMessage(body, resp.statusText), body);
    }
    return resp.json() as Promise<{ access_token: string; must_change_password: boolean; user: User }>;
  },
  fileCapabilities: () =>
    userRequest<FileCapabilityRegistryResponse>('/api/v1/workspaces/file-capabilities'),
  changeOwnPassword: async (token: string, oldPassword: string, newPassword: string) => {
    const resp = await fetch(`${BASE_URL}/api/v1/users/change-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({}));
      throw new ApiError(resp.status, responseErrorMessage(body, resp.statusText), body);
    }
    return resp.json() as Promise<{ access_token: string; must_change_password: boolean; user: User }>;
  },
  me: () => userRequest<TerminalUser>('/api/v1/terminal/me'),
  effectiveAccess: () => userRequest<EffectiveAccess>('/api/v1/terminal/effective-access'),
  resources: () => userRequest<TerminalResources>('/api/v1/terminal/resources'),
  models: () => userRequest<TerminalModels>('/api/v1/terminal/models'),
  agents: () => userRequest<{ agents: TerminalAgent[] }>('/api/v1/terminal/agents'),
  applications: () => userRequest<TerminalEnterpriseApplication[]>('/api/v1/terminal/applications'),
  launchApplication: (id: string, moduleKey?: string, pageKey?: string) => {
    const params = new URLSearchParams();
    if (moduleKey) params.set('module_key', moduleKey);
    if (pageKey) params.set('page_key', pageKey);
    const query = params.toString();
    return userRequest<EnterpriseApplicationLaunch>(
      `/api/v1/terminal/applications/${id}/launch${query ? `?${query}` : ''}`,
      { method: 'POST', cache: 'no-store' },
    );
  },
  invokeApplicationAction: (
    id: string, actionKey: string, data: { module_key: string; page_key?: string; params: Record<string, unknown>; request_id?: string },
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
  createSubsystemAiRun: (data: {
    applicationId: string;
    moduleKey: string;
    pageKey: string;
    actionKey: string;
    capability: SubsystemAiRun['capability'];
    instruction: string;
    context: Record<string, unknown>;
    textInput: string;
    requestId: string;
    files: Array<{ name: string; mimeType: string; blob: Blob }>;
  }) => {
    const form = new FormData();
    form.append('application_id', data.applicationId);
    form.append('module_key', data.moduleKey);
    form.append('page_key', data.pageKey);
    form.append('action_key', data.actionKey);
    form.append('capability', data.capability);
    form.append('instruction', data.instruction);
    form.append('context_json', JSON.stringify(data.context));
    form.append('text_input', data.textInput);
    form.append('request_id', data.requestId);
    for (const file of data.files) {
      form.append('files', file.blob, file.name);
    }
    return userRequest<{ run_id: string; request_id: string; status: string }>(
      '/api/v1/subsystem-ai/runs',
      { method: 'POST', body: form },
    );
  },
  getSubsystemAiRun: (runId: string) =>
    userRequest<SubsystemAiRun>(`/api/v1/subsystem-ai/runs/${runId}`),
  cancelSubsystemAiRun: (runId: string) =>
    userRequest<SubsystemAiRun>(`/api/v1/subsystem-ai/runs/${runId}/cancel`, { method: 'POST' }),
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
  scopeNodes: () => userRequest<ScopeNode[]>('/api/v1/terminal/scope-nodes'),
  memory: () => userRequest<TerminalMemoryItem[]>('/api/v1/terminal/memory'),
  listTasks: (query?: string | { q?: string; applicationId?: string; limit?: number; offset?: number }) => {
    const values = typeof query === 'string' ? { q: query } : (query ?? {});
    const params = new URLSearchParams();
    if (values.q?.trim()) params.set('q', values.q.trim());
    if ('applicationId' in values && values.applicationId) params.set('application_id', values.applicationId);
    if ('limit' in values && values.limit) params.set('limit', String(values.limit));
    if ('offset' in values && values.offset) params.set('offset', String(values.offset));
    const suffix = params.toString();
    return userRequest<TerminalTask[]>(`/api/v1/terminal/tasks${suffix ? `?${suffix}` : ''}`);
  },
  createTask: (data: { title?: string; message: string; config: TaskConfig }) =>
    userRequest<TerminalTask>('/api/v1/terminal/tasks', { method: 'POST', body: JSON.stringify(data) }),
  getTask: (id: string, applicationId?: string) => userRequest<TerminalTaskWithMessages>(
    `/api/v1/terminal/tasks/${id}${applicationId ? `?application_id=${encodeURIComponent(applicationId)}` : ''}`,
  ),
  updateTask: (id: string, data: Partial<{ title: string; status: string; config: TaskConfig }>) =>
    userRequest<TerminalTask>(`/api/v1/terminal/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteTask: (id: string) => userRequest<void>(`/api/v1/terminal/tasks/${id}`, { method: 'DELETE' }),
  /** 删除一整轮对话（user+assistant 消息）；已交付到工作空间的文件保持不变。 */
  deleteTaskMessage: (taskId: string, messageId: string) =>
    userRequest<void>(`/api/v1/terminal/tasks/${taskId}/messages/${messageId}`, { method: 'DELETE' }),
  runTask: (
    id: string, message: string, template_agent_id?: string | null,
    attachment_file_ids: string[] = [],
    application_id?: string | null, page_context: Record<string, unknown> = {},
    file_refs_v1: WorkspaceFileRefV1[] = [],
    target_workspace_id?: string | null, client_request_id?: string,
  ) =>
    userRequest<{ assistant: string; steps: unknown[]; usage: Record<string, number>; run_id: number; latency_ms: number }>(
      `/api/v1/terminal/tasks/${id}/run`,
      { method: 'POST', body: JSON.stringify({ message, stream: false, template_agent_id: template_agent_id ?? null, application_id: application_id ?? null, page_context, target_workspace_id: target_workspace_id ?? null, client_request_id: client_request_id ?? crypto.randomUUID(), ...buildTaskRunFilePayload(attachment_file_ids, file_refs_v1) }) },
    ),
  /** 流式执行：返回原始 Response，由调用方解析持久化 SSE 事件。
   *  template_agent_id 逐次覆盖（不落库）：undefined=沿用 task.config；null=通用；UUID=该次用此智能体。 */
  runTaskStream: (
    id: string, message: string, signal: AbortSignal,
    template_agent_id?: string | null, attachment_file_ids: string[] = [],
    application_id?: string | null,
    page_context: Record<string, unknown> = {},
    file_refs_v1: WorkspaceFileRefV1[] = [],
    target_workspace_id?: string | null, client_request_id?: string,
  ) =>
    fetch(`${BASE_URL}/api/v1/terminal/tasks/${id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${sessionStorage.getItem(USER_TOKEN_KEY) || ''}` },
      body: JSON.stringify({ message, stream: true, template_agent_id: template_agent_id ?? null, application_id: application_id ?? null, page_context, target_workspace_id: target_workspace_id ?? null, client_request_id: client_request_id ?? crypto.randomUUID(), ...buildTaskRunFilePayload(attachment_file_ids, file_refs_v1) }),
      signal,
    }),
  /** resume：重连/回放一个运行中或已完成的 run（后台 detach 执行，刷新不丢）。 */
  streamTask: (id: string, signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/v1/terminal/tasks/${id}/stream`, {
      method: 'GET',
      headers: { Authorization: `Bearer ${sessionStorage.getItem(USER_TOKEN_KEY) || ''}` },
      signal,
    }),
  streamWorkspaceFileEvents: (after: number, signal: AbortSignal) =>
    fetch(`${BASE_URL}/api/v1/terminal/file-events/stream?after=${Math.max(0, Math.trunc(after))}`, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        Authorization: `Bearer ${sessionStorage.getItem(USER_TOKEN_KEY) || ''}`,
      },
      cache: 'no-store',
      signal,
    }),
  /** 取消运行中的 run（真停后台 asyncio.Task，非仅断读端）。 */
  cancelTask: (id: string) =>
    userRequest<{ cancelled: boolean }>(`/api/v1/terminal/tasks/${id}/cancel`, { method: 'POST' }),
  /** 对高风险工具的审批请求做决定（允许本次 / 拒绝）。
   *  404 = 审批不存在或已过期；409 = 已被处理（其他端已决定或已超时）。调用方按 ApiError.status 区分。 */
  decideApproval: (taskId: string, approvalId: string, decision: TerminalApprovalDecision) =>
    userRequest<{ outcome: TerminalApprovalOutcome }>(
      `/api/v1/terminal/tasks/${taskId}/approvals/${approvalId}`,
      { method: 'POST', body: JSON.stringify({ decision }) },
    ),
  listWsFilesPage: (wsId: string, page = 1, pageSize = 100) =>
    userRequest<WorkspaceFilePage>(`/api/v1/terminal/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`),
  listWsFiles: (wsId: string) => loadAllWorkspaceFilePages((page, pageSize) =>
    userRequest<WorkspaceFilePage>(`/api/v1/terminal/workspaces/${wsId}/files?page=${page}&page_size=${pageSize}`)),
  /** 用户可访问的全部工作空间文件（企业/部门/个人并集），供任务输入框 @ 引用下拉。 */
  listAllWsFiles: () => userRequest<WorkspaceFileSummary[]>('/api/v1/terminal/workspace-files'),
  upsertWsFile: (wsId: string, data: { path: string; content: string; metadata?: Record<string, unknown> }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/workspaces/${wsId}/files`, { method: 'POST', body: JSON.stringify(data) }),
  uploadWsFile: (wsId: string, file: File, path: string, options?: WorkspaceUploadOptions) =>
    uploadTerminalWorkspaceFile(wsId, file, path, options),
  getWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`),
  getWsFilePreview: (id: string) => userRequest<WorkspaceFilePreview>(`/api/v1/terminal/files/${id}/preview`),
  getWsFileOriginalPreviewSource: (id: string, versionId?: string) =>
    userRequest<WorkspaceOriginalPreviewSource>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/original-preview-source`, versionId)),
  createWsFilePreviewSession: (id: string, clientOpenId: string, preferredMode: WorkspacePreviewPreferredMode = 'default', versionId?: string) =>
    userRequest<WorkspacePreviewSession>(`/api/v1/terminal/files/${id}/preview-session`, {
      method: 'POST', body: JSON.stringify({ client_open_id: clientOpenId, preferred_mode: preferredMode, version_id: versionId }),
    }),
  refreshWsFilePreviewSession: (id: string, accessToken: string, refreshToken: string, refreshContext: string) =>
    userRequest<WorkspacePreviewSession>(`/api/v1/terminal/files/${id}/preview-session/refresh`, {
      method: 'POST', body: JSON.stringify({ access_token: accessToken, refresh_token: refreshToken, refresh_context: refreshContext }),
    }),
  startWsFileFallbackPreview: (id: string, versionId?: string) =>
    userRequest<WorkspaceFallbackPreview>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/fallback-preview`, versionId), { method: 'POST' }),
  getWsFileFallbackPreview: (id: string, versionId?: string) =>
    userRequest<WorkspaceFallbackPreview>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/fallback-preview`, versionId)),
  startWsFileSpreadsheetPreview: (id: string, versionId?: string) =>
    userRequest<WorkspaceSpreadsheetPreview>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/spreadsheet-preview`, versionId), { method: 'POST' }),
  getWsFileSpreadsheetPreview: (id: string, versionId?: string) =>
    userRequest<WorkspaceSpreadsheetPreview>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/spreadsheet-preview`, versionId)),
  getWsFileSpreadsheetPage: (id: string, sheet: string, page: number, versionId?: string) =>
    userRequest<WorkspaceSpreadsheetPage>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/spreadsheet-preview/sheets/${encodeURIComponent(sheet)}/pages/${page}`, versionId)),
  getWsFileDownloadTicket: (id: string, versionId?: string) =>
    userRequest<WorkspaceDownloadTicket>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/download-ticket`, versionId), { method: 'POST' }),
  getWsFilePdfPreviewInfo: (id: string, versionId?: string) =>
    userRequest<WorkspacePdfPreviewInfo>(withWorkspaceVersion(`/api/v1/terminal/files/${id}/pdf-preview/info`, versionId)),
  getWsFilePdfPreviewPage: (id: string, pageNumber: number, versionId?: string) =>
    requestBlob(withWorkspaceVersion(`/api/v1/terminal/files/${id}/pdf-preview/pages/${pageNumber}`, versionId), USER_TOKEN_KEY),
  getWsFileOriginalPreview: (id: string, signalOrVersion?: AbortSignal | string, versionId?: string) => {
    const signal = typeof signalOrVersion === 'string' ? undefined : signalOrVersion;
    const selectedVersion = typeof signalOrVersion === 'string' ? signalOrVersion : versionId;
    return requestBlob(withWorkspaceVersion(`/api/v1/terminal/files/${id}/original-preview`, selectedVersion), USER_TOKEN_KEY, signal);
  },
  downloadWsFile: (id: string, signalOrVersion?: AbortSignal | string, versionId?: string) => {
    const signal = typeof signalOrVersion === 'string' ? undefined : signalOrVersion;
    const selectedVersion = typeof signalOrVersion === 'string' ? signalOrVersion : versionId;
    return requestBlob(withWorkspaceVersion(`/api/v1/terminal/files/${id}/download`, selectedVersion), USER_TOKEN_KEY, signal);
  },
  reparseWsFile: (id: string) => userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/reparse`, { method: 'POST' }),
  updateWsFile: (id: string, data: {
    path: string; content: string; metadata?: Record<string, unknown>;
    base_version_id?: string | null; idempotency_key?: string;
  }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  deleteWsFile: (id: string, data: { base_version_id: string; idempotency_key: string }) =>
    userRequest<void>(`/api/v1/terminal/files/${id}`, {
      method: 'DELETE', body: JSON.stringify(data),
    }),
  listWsFileVersions: (id: string) => userRequest<Array<{
    id: string; workspace_file_id: string; version_no: number; size: number;
    content_hash: string | null; parse_status: string; parse_kind: string | null;
    parse_error: string | null; created_at: string;
  }>>(`/api/v1/terminal/files/${id}/versions`),
  getWsFileVersion: (id: string, versionId: string) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/versions/${versionId}`),
  restoreWsFileVersion: (id: string, versionId: string, options: { base_version_id: string; idempotency_key: string }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/files/${id}/versions/${versionId}/restore`, {
      method: 'POST', body: JSON.stringify(options),
    }),
  listWsTrash: (wsId: string) => userRequest<WorkspaceFile[]>(`/api/v1/terminal/workspaces/${wsId}/trash`),
  listWsAudit: (wsId: string, limit = 200) =>
    userRequest<WorkspaceAuditEvent[]>(`/api/v1/terminal/workspaces/${wsId}/audit?limit=${limit}`),
  restoreWsTrash: (wsId: string, fileId: string, options: { base_version_id: string; idempotency_key: string }) =>
    userRequest<WorkspaceFile>(`/api/v1/terminal/workspaces/${wsId}/trash/${fileId}/restore`, {
      method: 'POST', body: JSON.stringify(options),
    }),
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
  node_type: 'organization' | 'department' | 'user';
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
