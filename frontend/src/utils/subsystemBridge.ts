const BRIDGE_MAX_BYTES = 16_384;
const BRIDGE_AI_MAX_BYTES = 128 * 1024;
const BRIDGE_AI_MAX_FILE_BYTES = 20 * 1024 * 1024;
const BRIDGE_AI_MAX_FILES = 5;
const BRIDGE_KEY_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,255}$/;
const BRIDGE_REQUEST_ID_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{7,119}$/;
const BRIDGE_CONTEXT_KEYS = new Set([
  'type', 'version', 'launch_nonce', 'application_slug',
  'enterprise_key', 'route', 'module_key', 'module_name',
  'page_key', 'page_name', 'entity_type', 'entity_id',
  'filters', 'selection', 'data_version',
]);
const BRIDGE_READY_KEYS = new Set(['type', 'version', 'launch_nonce', 'application_slug']);
const BRIDGE_REFRESH_KEYS = new Set([
  'type', 'version', 'launch_nonce', 'application_slug',
  'module_key', 'page_key', 'request_id',
]);
const BRIDGE_REFRESH_RESULT_KEYS = new Set([
  'type', 'version', 'launch_nonce', 'application_slug',
  'module_key', 'page_key', 'request_id', 'status', 'data_version', 'error',
]);
const BRIDGE_AI_RUN_KEYS = new Set([
  'type', 'version', 'launch_nonce', 'application_slug', 'module_key', 'page_key',
  'action_key', 'request_id', 'capability', 'instruction', 'context', 'text_input', 'files',
]);
const BRIDGE_AI_FILE_KEYS = new Set(['name', 'mime_type', 'blob']);
const BRIDGE_STRING_KEYS = new Set([
  'enterprise_key', 'application_slug', 'route', 'module_key', 'module_name',
  'page_key', 'page_name', 'entity_type', 'entity_id',
]);

export interface BridgeExpectation {
  applicationSlug: string;
  launchNonce: string;
}

export interface BridgeRefreshExpectation extends BridgeExpectation {
  moduleKey: string;
  pageKey: string;
  requestId: string;
}

export type BridgeAiCapability =
  | 'vision.ocr'
  | 'vision.compare'
  | 'vision.classify'
  | 'speech.transcribe'
  | 'text.extract'
  | 'business.predict';

export type BridgeAiRunRequest = {
  moduleKey: string;
  pageKey: string;
  actionKey: string;
  requestId: string;
  capability: BridgeAiCapability;
  instruction: string;
  context: Record<string, unknown>;
  textInput: string;
  files: Array<{ name: string; mimeType: string; blob: Blob }>;
};

export type BridgeRefreshResult = {
  status: 'completed' | 'deferred' | 'failed';
  dataVersion?: string | number;
  error?: string;
};

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function hasOnlyKeys(value: Record<string, unknown>, allowedKeys: Set<string>): boolean {
  return Object.keys(value).every((key) => allowedKeys.has(key));
}

function fitsEnvelope(value: Record<string, unknown>): boolean {
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength <= BRIDGE_MAX_BYTES;
  } catch {
    return false;
  }
}

function fitsAiEnvelope(value: Record<string, unknown>): boolean {
  try {
    const metadataOnly = {
      ...value,
      files: Array.isArray(value.files)
        ? value.files.map((item) => isPlainObject(item) ? {
          name: item.name,
          mime_type: item.mime_type,
          size: item.blob instanceof Blob ? item.blob.size : -1,
        } : null)
        : [],
    };
    return new TextEncoder().encode(JSON.stringify(metadataOnly)).byteLength <= BRIDGE_AI_MAX_BYTES;
  } catch {
    return false;
  }
}

function hasExpectedIdentity(value: Record<string, unknown>, expected: BridgeExpectation): boolean {
  return value.application_slug === expected.applicationSlug && value.launch_nonce === expected.launchNonce;
}

function isSafeBridgeValue(value: unknown, depth = 0): boolean {
  if (depth > 5) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return value.length <= 4_000;
  if (Array.isArray(value)) return value.length <= 200 && value.every((item) => isSafeBridgeValue(item, depth + 1));
  if (!isPlainObject(value) || Object.keys(value).length > 200) return false;
  return Object.entries(value).every(([key, item]) => (
    key.length > 0
    && key.length <= 128
    && key !== '__proto__'
    && key !== 'prototype'
    && key !== 'constructor'
    && isSafeBridgeValue(item, depth + 1)
  ));
}

function isSafeRoute(route: string): boolean {
  return route.startsWith('/')
    && !route.startsWith('//')
    && !route.includes('\\')
    && !/[\u0000-\u001f\u007f]/.test(route)
    && route.length <= 1_000;
}

export function isBridgeReady(value: unknown, expected: BridgeExpectation): boolean {
  return isPlainObject(value)
    && hasOnlyKeys(value, BRIDGE_READY_KEYS)
    && fitsEnvelope(value)
    && value.type === 'zhuojian:ready'
    && value.version === 1
    && hasExpectedIdentity(value, expected);
}

export function parseBridgeContext(value: unknown, expected: BridgeExpectation): Record<string, unknown> | null {
  if (
    !isPlainObject(value)
    || !hasOnlyKeys(value, BRIDGE_CONTEXT_KEYS)
    || !fitsEnvelope(value)
    || value.type !== 'zhuojian:context'
    || value.version !== 1
    || !hasExpectedIdentity(value, expected)
  ) return null;

  const context: Record<string, unknown> = {
    bridge_version: 1,
    application_slug: expected.applicationSlug,
  };
  for (const key of BRIDGE_STRING_KEYS) {
    const item = value[key];
    if (item === undefined || item === null) continue;
    if (typeof item !== 'string' || item.length > 1_000) return null;
    if ((key === 'module_key' || key === 'page_key') && !BRIDGE_KEY_PATTERN.test(item)) return null;
    if (key === 'entity_type' && item && !BRIDGE_KEY_PATTERN.test(item)) return null;
    if (key === 'route' && !isSafeRoute(item)) return null;
    // The enterprise identity always comes from the authenticated host
    // session. A child frame may describe it, but must never override it.
    if (key === 'enterprise_key') continue;
    if (item || (key !== 'entity_type' && key !== 'entity_id')) context[key] = item;
  }
  for (const key of ['filters', 'selection']) {
    const item = value[key];
    if (item === undefined || item === null) continue;
    if (!isPlainObject(item) || !isSafeBridgeValue(item)) return null;
    context[key] = item;
  }
  const dataVersion = value.data_version;
  if (dataVersion !== undefined && dataVersion !== null) {
    if (
      (typeof dataVersion !== 'string' && typeof dataVersion !== 'number')
      || (typeof dataVersion === 'string' && dataVersion.length > 1_000)
      || (typeof dataVersion === 'number' && !Number.isFinite(dataVersion))
    ) return null;
    context.data_version = dataVersion;
  }
  return context;
}

export function buildHostReadyMessage(
  expected: BridgeExpectation,
  allowedModuleKeys: string[],
  allowedPageKeys: string[],
) {
  return {
    type: 'zhuojian:host-ready' as const,
    version: 1 as const,
    launch_nonce: expected.launchNonce,
    application_slug: expected.applicationSlug,
    allowed_module_keys: allowedModuleKeys.filter((key) => BRIDGE_KEY_PATTERN.test(key)),
    allowed_page_keys: allowedPageKeys.filter((key) => BRIDGE_KEY_PATTERN.test(key)),
  };
}

export function buildRefreshMessage(expected: BridgeRefreshExpectation) {
  if (
    !BRIDGE_KEY_PATTERN.test(expected.moduleKey)
    || !BRIDGE_KEY_PATTERN.test(expected.pageKey)
    || !BRIDGE_KEY_PATTERN.test(expected.requestId)
  ) throw new Error('静默刷新消息包含无效标识');
  const value = {
    type: 'zhuojian:refresh' as const,
    version: 1 as const,
    launch_nonce: expected.launchNonce,
    application_slug: expected.applicationSlug,
    module_key: expected.moduleKey,
    page_key: expected.pageKey,
    request_id: expected.requestId,
  };
  if (!hasOnlyKeys(value, BRIDGE_REFRESH_KEYS) || !fitsEnvelope(value)) {
    throw new Error('静默刷新消息超过协议限制');
  }
  return value;
}

export function parseBridgeRefreshResult(
  value: unknown,
  expected: BridgeRefreshExpectation,
): BridgeRefreshResult | null {
  if (
    !isPlainObject(value)
    || !hasOnlyKeys(value, BRIDGE_REFRESH_RESULT_KEYS)
    || !fitsEnvelope(value)
    || value.type !== 'zhuojian:refresh-result'
    || value.version !== 1
    || !hasExpectedIdentity(value, expected)
    || value.module_key !== expected.moduleKey
    || value.page_key !== expected.pageKey
    || value.request_id !== expected.requestId
    || !['completed', 'deferred', 'failed'].includes(String(value.status))
  ) return null;
  const dataVersion = value.data_version;
  if (
    dataVersion !== undefined
    && dataVersion !== null
    && (
      (typeof dataVersion !== 'string' && typeof dataVersion !== 'number')
      || (typeof dataVersion === 'string' && dataVersion.length > 1_000)
      || (typeof dataVersion === 'number' && !Number.isFinite(dataVersion))
    )
  ) return null;
  const error = value.error;
  if (error !== undefined && error !== null && (typeof error !== 'string' || error.length > 1_000)) return null;
  return {
    status: value.status as BridgeRefreshResult['status'],
    ...(dataVersion !== undefined && dataVersion !== null ? { dataVersion } : {}),
    ...(typeof error === 'string' && error ? { error } : {}),
  };
}


export function parseBridgeAiRun(
  value: unknown,
  expected: BridgeExpectation,
): BridgeAiRunRequest | null {
  if (
    !isPlainObject(value)
    || !hasOnlyKeys(value, BRIDGE_AI_RUN_KEYS)
    || !fitsAiEnvelope(value)
    || value.type !== 'zhuojian:ai-run'
    || value.version !== 1
    || !hasExpectedIdentity(value, expected)
  ) return null;
  const moduleKey = typeof value.module_key === 'string' ? value.module_key : '';
  const pageKey = typeof value.page_key === 'string' ? value.page_key : '';
  const actionKey = typeof value.action_key === 'string' ? value.action_key : '';
  const requestId = typeof value.request_id === 'string' ? value.request_id : '';
  const capabilities = new Set<BridgeAiCapability>([
    'vision.ocr', 'vision.compare', 'vision.classify',
    'speech.transcribe', 'text.extract', 'business.predict',
  ]);
  if (
    !BRIDGE_KEY_PATTERN.test(moduleKey)
    || !BRIDGE_KEY_PATTERN.test(pageKey)
    || !BRIDGE_KEY_PATTERN.test(actionKey)
    || !BRIDGE_REQUEST_ID_PATTERN.test(requestId)
    || typeof value.capability !== 'string'
    || !capabilities.has(value.capability as BridgeAiCapability)
  ) return null;
  const instruction = value.instruction === undefined ? '' : value.instruction;
  const textInput = value.text_input === undefined ? '' : value.text_input;
  const context = value.context === undefined ? {} : value.context;
  if (
    typeof instruction !== 'string' || instruction.length > 4_000
    || typeof textInput !== 'string' || textInput.length > 100_000
    || !isPlainObject(context) || !isSafeBridgeValue(context)
  ) return null;
  const rawFiles = value.files === undefined ? [] : value.files;
  if (!Array.isArray(rawFiles) || rawFiles.length > BRIDGE_AI_MAX_FILES) return null;
  let totalBytes = 0;
  const files: BridgeAiRunRequest['files'] = [];
  for (const item of rawFiles) {
    if (!isPlainObject(item) || !hasOnlyKeys(item, BRIDGE_AI_FILE_KEYS)) return null;
    if (
      typeof item.name !== 'string' || !item.name || item.name.length > 255
      || /[\\/\u0000-\u001f\u007f]/.test(item.name)
      || typeof item.mime_type !== 'string' || item.mime_type.length > 160
      || !(item.blob instanceof Blob) || item.blob.size <= 0
    ) return null;
    totalBytes += item.blob.size;
    if (totalBytes > BRIDGE_AI_MAX_FILE_BYTES) return null;
    files.push({ name: item.name, mimeType: item.mime_type, blob: item.blob });
  }
  return {
    moduleKey,
    pageKey,
    actionKey,
    requestId,
    capability: value.capability as BridgeAiCapability,
    instruction,
    context,
    textInput,
    files,
  };
}
