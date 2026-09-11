/** Both assistant views address the same task; application context is per turn. */
export function conversationIdFromRoute(taskId: string | undefined, search: string): string | null {
  const params = new URLSearchParams(search);
  return params.get('view') === 'application'
    ? params.get('conversation') || taskId || null
    : taskId || null;
}

export function applicationConversationRoute(
  base: string, applicationId: string, moduleKey: string, pageKey: string | null,
  conversationId: string | null,
): string {
  const params = new URLSearchParams({ view: 'application', app: applicationId, module: moduleKey });
  if (pageKey) params.set('page', pageKey);
  if (conversationId) params.set('conversation', conversationId);
  return `${base}?${params}`;
}
