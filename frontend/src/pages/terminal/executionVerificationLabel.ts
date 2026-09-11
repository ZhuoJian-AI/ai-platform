/** Tool receipts describe calls, never whether the user's whole goal was met. */
export function executionVerificationLabel(status: string): string {
  const labels: Record<string, string> = {
    verified: '工具调用成功',
    recovered: '工具调用已恢复（有重试）',
    partial: '部分工具调用失败',
    failed: '工具调用失败',
    legacy_unverified: '历史工具记录未验证',
  };
  return labels[status] ?? '工具状态未知';
}
