export function validateHttpsApplicationUrl(_: unknown, value?: string): Promise<void> {
  if (!value) return Promise.resolve();
  try {
    const url = new URL(value);
    if (url.protocol !== 'https:') return Promise.reject(new Error('生产应用地址必须使用 HTTPS'));
    if (url.username || url.password) return Promise.reject(new Error('应用地址不能包含用户名或密码'));
    if (url.hash) return Promise.reject(new Error('应用地址不能包含 URL 片段'));
    return Promise.resolve();
  } catch {
    return Promise.reject(new Error('请输入完整的 HTTPS 地址'));
  }
}
