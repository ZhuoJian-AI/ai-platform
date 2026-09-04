const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

const LEGACY_TOKEN_KEY = 'ai_infra_token';
const LEGACY_ADMIN_KEY = 'ai_infra_admin';
const ADMIN_ORG_SLUG_KEY = 'zhuojian:admin-organization-slug';
const ADMIN_SESSION_EXPIRED_EVENT = 'zhuojian:admin-session-expired';
const CSRF_COOKIE_NAMES = ['__Host-ai-infra-admin-csrf', 'ai_infra_admin_csrf'];
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

let inMemoryAccessToken: string | null = null;
let inMemoryCsrfToken: string | null = null;
let organizationRequestController = new AbortController();
const activeAdminXhrs = new Set<XMLHttpRequest>();

function browserStorage(): Pick<Window, 'localStorage' | 'sessionStorage'> | null {
  return typeof window === 'undefined' ? null : window;
}

function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const prefix = `${encodeURIComponent(name)}=`;
  const match = document.cookie.split(';').map((item) => item.trim()).find((item) => item.startsWith(prefix));
  if (!match) return null;
  try { return decodeURIComponent(match.slice(prefix.length)); } catch { return null; }
}

function csrfTokenFromCookie(): string | null {
  for (const name of CSRF_COOKIE_NAMES) {
    const token = readCookie(name);
    if (token) return token;
  }
  return null;
}

async function loadCsrfToken(): Promise<string | null> {
  const existing = inMemoryCsrfToken || csrfTokenFromCookie();
  if (existing) return existing;
  try {
    const response = await fetch(`${BASE_URL}/api/v1/auth/csrf`, {
      credentials: 'include',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) return null;
    const body = await response.json().catch(() => ({})) as { csrf_token?: unknown };
    const token = typeof body.csrf_token === 'string' ? body.csrf_token : csrfTokenFromCookie();
    if (token) inMemoryCsrfToken = token;
    return token || null;
  } catch {
    return null;
  }
}

function combineSignals(first?: AbortSignal | null, second?: AbortSignal | null): AbortSignal | undefined {
  if (!first) return second ?? undefined;
  if (!second) return first;
  if (first.aborted || second.aborted) return AbortSignal.abort();
  if (typeof AbortSignal.any === 'function') return AbortSignal.any([first, second]);
  const controller = new AbortController();
  const abort = () => controller.abort();
  first.addEventListener('abort', abort, { once: true });
  second.addEventListener('abort', abort, { once: true });
  return controller.signal;
}

function trustedAdminApiTarget(input: RequestInfo | URL): boolean {
  if (typeof window === 'undefined') return true;
  try {
    const apiOrigin = new URL(BASE_URL || window.location.origin, window.location.origin).origin;
    const rawTarget = input instanceof Request ? input.url : input.toString();
    return new URL(rawTarget, window.location.origin).origin === apiOrigin;
  } catch {
    return false;
  }
}

/**
 * One-time compatibility bridge for deployments that previously persisted the
 * administrator JWT. The value is moved to process memory and erased before
 * React renders any authenticated page.
 */
export function migrateLegacyAdminSession(): { accessToken: string | null; organizationSlug: string | null } {
  const storage = browserStorage();
  if (!storage) return { accessToken: null, organizationSlug: null };
  const token = storage.localStorage.getItem(LEGACY_TOKEN_KEY);
  const serializedAdmin = storage.localStorage.getItem(LEGACY_ADMIN_KEY);
  let organizationSlug = storage.sessionStorage.getItem(ADMIN_ORG_SLUG_KEY);
  try {
    const candidate = serializedAdmin ? JSON.parse(serializedAdmin) as { organization_slug?: unknown } : null;
    organizationSlug = typeof candidate?.organization_slug === 'string' ? candidate.organization_slug : null;
  } catch { /* invalid legacy state is discarded below */ }
  storage.localStorage.removeItem(LEGACY_TOKEN_KEY);
  storage.localStorage.removeItem(LEGACY_ADMIN_KEY);
  if (token) inMemoryAccessToken = token;
  if (organizationSlug) storage.sessionStorage.setItem(ADMIN_ORG_SLUG_KEY, organizationSlug);
  return { accessToken: inMemoryAccessToken, organizationSlug };
}

export function setAdminSession(accessToken: string | null, organizationSlug?: string | null, csrfToken?: string | null) {
  const storage = browserStorage();
  inMemoryAccessToken = accessToken || null;
  inMemoryCsrfToken = csrfToken || csrfTokenFromCookie();
  storage?.localStorage.removeItem(LEGACY_TOKEN_KEY);
  storage?.localStorage.removeItem(LEGACY_ADMIN_KEY);
  if (!storage) return;
  if (organizationSlug) storage.sessionStorage.setItem(ADMIN_ORG_SLUG_KEY, organizationSlug);
  else storage.sessionStorage.removeItem(ADMIN_ORG_SLUG_KEY);
}

export function clearAdminSession() {
  const storage = browserStorage();
  inMemoryAccessToken = null;
  inMemoryCsrfToken = null;
  storage?.localStorage.removeItem(LEGACY_TOKEN_KEY);
  storage?.localStorage.removeItem(LEGACY_ADMIN_KEY);
  storage?.sessionStorage.removeItem(ADMIN_ORG_SLUG_KEY);
}

export function getAdminOrganizationSlug(): string | null {
  return browserStorage()?.sessionStorage.getItem(ADMIN_ORG_SLUG_KEY) ?? null;
}

export function getAdminAccessToken(): string | null {
  return inMemoryAccessToken;
}

export function setAdminCsrfToken(token: string | null | undefined) {
  inMemoryCsrfToken = token || csrfTokenFromCookie();
}

/** Abort in-flight requests before switching to another enterprise context. */
export function rotateAdminOrganizationScope() {
  organizationRequestController.abort();
  organizationRequestController = new AbortController();
  for (const xhr of activeAdminXhrs) xhr.abort();
  activeAdminXhrs.clear();
}

function notifySessionExpired() {
  clearAdminSession();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(ADMIN_SESSION_EXPIRED_EVENT));
}

export function onAdminSessionExpired(listener: () => void): () => void {
  if (typeof window === 'undefined') return () => undefined;
  window.addEventListener(ADMIN_SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(ADMIN_SESSION_EXPIRED_EVENT, listener);
}

export interface AdminFetchOptions {
  /** Authentication probes use false so an expected 401 does not emit a global logout. */
  notifyOnUnauthorized?: boolean;
  /** Login/logout/session bootstrap must survive an enterprise selector change. */
  organizationScoped?: boolean;
}

export async function adminFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options: AdminFetchOptions = {},
): Promise<Response> {
  if (!trustedAdminApiTarget(input)) throw new TypeError('Administrator credentials may only be sent to the configured API origin');
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (inMemoryAccessToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${inMemoryAccessToken}`);
  }
  if (!SAFE_METHODS.has(method) && !headers.has('X-CSRF-Token')) {
    const csrfToken = await loadCsrfToken();
    if (csrfToken) headers.set('X-CSRF-Token', csrfToken);
  }
  const scopeSignal = options.organizationScoped === false ? undefined : organizationRequestController.signal;
  const response = await fetch(input, {
    ...init,
    credentials: 'include',
    headers,
    signal: combineSignals(init.signal, scopeSignal),
  });
  if (response.status === 401 && options.notifyOnUnauthorized !== false) notifySessionExpired();
  return response;
}

/** Configure an authenticated multipart XHR without persisting bearer tokens. */
export async function authorizeAdminXhr(xhr: XMLHttpRequest, method = 'POST'): Promise<() => void> {
  xhr.withCredentials = true;
  if (inMemoryAccessToken) xhr.setRequestHeader('Authorization', `Bearer ${inMemoryAccessToken}`);
  if (!SAFE_METHODS.has(method.toUpperCase())) {
    const csrfToken = await loadCsrfToken();
    if (csrfToken) xhr.setRequestHeader('X-CSRF-Token', csrfToken);
  }
  activeAdminXhrs.add(xhr);
  const release = () => activeAdminXhrs.delete(xhr);
  xhr.addEventListener('loadend', release, { once: true });
  return release;
}

export function handleAdminXhrUnauthorized(status: number) {
  if (status === 401) notifySessionExpired();
}
