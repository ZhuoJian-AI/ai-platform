type StatusError = Error & { status?: unknown };

function errorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const status = (error as StatusError).status;
  return typeof status === 'number' ? status : undefined;
}

export function loginErrorMessage(error: unknown): string {
  const status = errorStatus(error);
  if (status === 401) return '用户名或密码错误，请重新输入';
  if (status === 429) return '登录尝试次数过多，请稍后再试';
  if (status !== undefined && status >= 500) return '登录服务暂时不可用，请稍后再试';
  if (error instanceof TypeError) return '无法连接登录服务，请检查网络后重试';

  const message = error instanceof Error ? error.message.trim() : '';
  if (/invalid (?:organization, )?username or password/i.test(message)) {
    return '用户名或密码错误，请重新输入';
  }
  return message || '登录失败，请稍后再试';
}

export function loginResponseError(status: number, detail: unknown): Error {
  const error = new Error(typeof detail === 'string' && detail.trim() ? detail : '登录失败') as StatusError;
  error.status = status;
  return error;
}
