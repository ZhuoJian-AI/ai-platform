import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { transform } from 'esbuild';

const tempDirectory = await mkdtemp(join(tmpdir(), 'zhuojian-login-feedback-'));

try {
  const source = await readFile(resolve('src/auth/loginFeedback.ts'), 'utf8');
  const compiled = await transform(source, { loader: 'ts', format: 'esm', target: 'es2022' });
  const modulePath = join(tempDirectory, 'loginFeedback.mjs');
  await writeFile(modulePath, compiled.code, 'utf8');
  const feedback = await import(`${pathToFileURL(modulePath).href}?v=${Date.now()}`);

  assert.equal(feedback.loginErrorMessage({ status: 401 }), '用户名或密码错误，请重新输入');
  assert.equal(feedback.loginErrorMessage({ status: 429 }), '登录尝试次数过多，请稍后再试');
  assert.equal(feedback.loginErrorMessage({ status: 503 }), '登录服务暂时不可用，请稍后再试');
  assert.equal(feedback.loginErrorMessage(new TypeError('Failed to fetch')), '无法连接登录服务，请检查网络后重试');
  assert.equal(
    feedback.loginErrorMessage(new Error('Invalid username or password')),
    '用户名或密码错误，请重新输入',
  );

  const adminLogin = await readFile(resolve('src/components/LoginForm.tsx'), 'utf8');
  const employeeLogin = await readFile(resolve('src/pages/terminal/UserLoginPage.tsx'), 'utf8');
  assert.match(adminLogin, /loginErrorMessage\(reason\)/);
  assert.match(adminLogin, /onValuesChange=\{\(\) => setError\(''\)\}/);
  assert.match(employeeLogin, /message=\{loginError\}/);
  assert.match(employeeLogin, /onValuesChange=\{\(\) => setLoginError\(''\)\}/);

  process.stdout.write('login feedback tests passed\n');
} finally {
  await rm(tempDirectory, { recursive: true, force: true });
}
