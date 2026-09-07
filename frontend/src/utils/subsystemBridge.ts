const BRIDGE_MAX_BYTES = 16_384;
const BRIDGE_KEY_PATTERN = /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,255}$/;
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
