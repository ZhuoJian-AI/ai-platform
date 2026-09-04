import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

class MemoryStorage {
  #values = new Map();
  getItem(key) { return this.#values.get(key) ?? null; }
  setItem(key, value) { this.#values.set(key, String(value)); }
  removeItem(key) { this.#values.delete(key); }
}

const tempDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-admin-session-'));
const originalWindow = globalThis.window;
const originalDocument = globalThis.document;
const originalFetch = globalThis.fetch;

try {
  const source = (await readFile(resolve('src/auth/adminSession.ts'), 'utf8'))
    .replace("const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';", "const BASE_URL = '';");
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(tempDirectory, 'adminSession.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');

  const localStorage = new MemoryStorage();
  const sessionStorage = new MemoryStorage();
  localStorage.setItem('ai_infra_token', 'legacy-secret');
  localStorage.setItem('ai_infra_admin', JSON.stringify({ organization_slug: 'alphabet' }));
  globalThis.window = {
    location: { origin: 'https://console.example' },
    localStorage,
    sessionStorage,
    dispatchEvent() {},
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.document = { cookie: 'ai_infra_admin_csrf=csrf-value' };

  const calls = [];
  globalThis.fetch = async (input, init = {}) => {
    calls.push({ input: input.toString(), init });
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } });
  };

  const session = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);
  const migrated = session.migrateLegacyAdminSession();
  assert.equal(migrated.accessToken, 'legacy-secret');
  assert.equal(migrated.organizationSlug, 'alphabet');
  assert.equal(localStorage.getItem('ai_infra_token'), null);
  assert.equal(localStorage.getItem('ai_infra_admin'), null);

  await session.adminFetch('/api/v1/organizations');
  assert.equal(new Headers(calls.at(-1).init.headers).get('Authorization'), 'Bearer legacy-secret');
  assert.equal(calls.at(-1).init.credentials, 'include');

  await session.adminFetch('/api/v1/organizations', { method: 'POST', body: '{}' });
  assert.equal(new Headers(calls.at(-1).init.headers).get('X-CSRF-Token'), 'csrf-value');

  await assert.rejects(
    () => session.adminFetch('https://attacker.example/collect'),
    /configured API origin/,
  );

  session.clearAdminSession();
  assert.equal(session.getAdminAccessToken(), null);

  const loginSource = await readFile(resolve('src/components/LoginForm.tsx'), 'utf8');
  const authContextSource = await readFile(resolve('src/context/AuthContext.tsx'), 'utf8');
  const appSource = await readFile(resolve('src/App.tsx'), 'utf8');
  assert.doesNotMatch(loginSource, /mfa_code|MFA_REQUIRED|must_change_password/);
  assert.match(loginSource, /login\(null, authenticatedAdmin, csrfToken\)/,
    'new administrator logins must rely on the HttpOnly cookie');
  assert.doesNotMatch(loginSource, /localStorage/);
  assert.doesNotMatch(authContextSource, /mfa_enrollment_required|AdminMfaEnrollment/);
  assert.match(appSource, /function AdminApp\(\)/);
  assert.match(appSource, /<Route path="\/:slug\/terminal\/login"/);
  assert.match(appSource, /<Route path="\/\*" element={<AdminApp \/>} \/>/,
    'employee routes must be resolved before the administrator provider is mounted');

  process.stdout.write('admin session tests passed\n');
} finally {
  globalThis.window = originalWindow;
  globalThis.document = originalDocument;
  globalThis.fetch = originalFetch;
  await rm(tempDirectory, { recursive: true, force: true });
}
