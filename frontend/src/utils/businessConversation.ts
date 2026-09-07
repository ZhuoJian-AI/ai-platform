export interface ApplicationConversationTask {
  id: string;
  config?: { application_id?: string | null } | null;
}

export function resolveBusinessConversationId(
  applicationId: string | null,
  applicationLoaded: boolean,
  selection: Record<string, string | null>,
  tasks: ApplicationConversationTask[],
): string | null {
  if (!applicationId) return null;
  if (Object.prototype.hasOwnProperty.call(selection, applicationId)) {
    return selection[applicationId] ?? null;
  }
  if (!applicationLoaded) return null;
  return tasks.find((task) => task.config?.application_id === applicationId)?.id ?? null;
}
