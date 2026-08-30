const BRIDGE_MAX_BYTES = 16_384;
const BRIDGE_STRING_KEYS = new Set([
  'enterprise_key', 'application_slug', 'route', 'module_key', 'module_name',
  'page_key', 'page_name', 'entity_type', 'entity_id',
]);

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function isSafeBridgeValue(value: unknown, depth = 0): boolean {
  if (depth > 5) return false;
  if (value === null || typeof value === 'boolean' || typeof value === 'number') return true;
  if (typeof value === 'string') return value.length <= 4_000;
  if (Array.isArray(value)) return value.length <= 200 && value.every((item) => isSafeBridgeValue(item, depth + 1));
  if (!isPlainObject(value) || Object.keys(value).length > 200) return false;
  return Object.entries(value).every(([key, item]) => key.length <= 128 && isSafeBridgeValue(item, depth + 1));
}

export function parseBridgeContext(value: unknown, applicationSlug: string): Record<string, unknown> | null {
  if (!isPlainObject(value) || value.type !== 'zhuojian:context' || value.version !== 1) return null;
  try {
    if (new TextEncoder().encode(JSON.stringify(value)).byteLength > BRIDGE_MAX_BYTES) return null;
  } catch { return null; }
  if (value.application_slug !== applicationSlug) return null;
  const context: Record<string, unknown> = { bridge_version: 1 };
  for (const key of BRIDGE_STRING_KEYS) {
    const item = value[key];
    if (item === undefined || item === null) continue;
    if (typeof item !== 'string' || item.length > 1000) return null;
    context[key] = item;
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
      || (typeof dataVersion === 'string' && dataVersion.length > 1000)
      || (typeof dataVersion === 'number' && !Number.isFinite(dataVersion))
    ) return null;
    context.data_version = dataVersion;
  }
  return context;
}
