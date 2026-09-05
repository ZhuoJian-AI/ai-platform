import { useEffect, useState } from 'react';
import { Button, Tag } from 'antd';
import {
  CheckCircleOutlined, ClockCircleOutlined, CloseCircleOutlined, DownOutlined,
  ExclamationCircleOutlined, LoadingOutlined, SafetyOutlined,
} from '@ant-design/icons';
import {
  terminal, ApiError,
  type TerminalApprovalDecidedBy, type TerminalApprovalDecision, type TerminalApprovalOutcome,
} from '../../api/client';

/** 一条高风险工具审批请求在时间线上的数据（由 SSE `approval_request` 落成 block，`approval_decided` 补 outcome）。 */
export interface ApprovalCardData {
  approvalId: string;
  tool: string;
  reason: string;
  argumentsPreview: string;
  /** ISO8601（UTC）；已过期且无 outcome 时按拒绝处理、不可操作。 */
  expiresAt: string;
  runId?: number;
  /** 由 SSE `approval_decided` 写入；优先于卡片本地状态。 */
  outcome?: TerminalApprovalOutcome;
  decidedBy?: TerminalApprovalDecidedBy;
}

// 与 Terminal.tsx 的 WB 配色 / ToolCard 卡片保持一致（组件独立于页面，故此处内联同一组色值）。
const COLORS = {
  border: '#E5E7EB',
  cardBg: '#FAFBFC',
  primary: '#6366F1',
  amber: '#b45309',
  amberBg: '#fffbeb',
  amberBorder: '#fde68a',
  green: '#22c55e',
  red: '#ef4444',
  gray: '#9ca3af',
  text: '#1f2937',
  muted: '#6b7280',
};

const OUTCOME_LABEL: Record<TerminalApprovalOutcome, string> = {
  'allowed-once': '已允许本次',
  rejected: '已拒绝',
  cancelled: '已取消',
  unavailable: '审批不可用',
};

const DECIDED_BY_LABEL: Record<TerminalApprovalDecidedBy, string> = {
  user: '用户',
  timeout: '超时',
  system: '系统',
};

// 卡片本地状态：仅记录本端 HTTP 决定的结果；SSE 下发的 outcome 一到即覆盖。
type LocalState =
  | { phase: 'idle' }
  | { phase: 'pending'; decision: TerminalApprovalDecision }
  | { phase: 'decided'; outcome: TerminalApprovalOutcome }
  | { phase: 'conflict' }   // 409：已被处理
  | { phase: 'gone' }       // 404：不存在 / 已过期
  | { phase: 'error'; message: string };

function remainingMs(expiresAt: string): number {
  const t = new Date(expiresAt).getTime();
  if (Number.isNaN(t)) return 0;
  return t - Date.now();
}

function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const mm = String(Math.floor(total / 60)).padStart(2, '0');
  const ss = String(total % 60).padStart(2, '0');
  return `${mm}:${ss}`;
}

// 最终展示态：由 SSE outcome > 本地 HTTP 结果 > 倒计时归零 依次决定。
type Resolved =
  | { state: 'actionable' }
  | { state: 'final'; label: string; tone: 'ok' | 'bad' | 'neutral'; note?: string };

function resolve(b: ApprovalCardData, local: LocalState, msLeft: number): Resolved {
  if (b.outcome) {
    if (b.decidedBy === 'timeout') return { state: 'final', label: '已超时，按拒绝处理', tone: 'bad' };
    const tone = b.outcome === 'allowed-once' ? 'ok' : b.outcome === 'rejected' ? 'bad' : 'neutral';
    const note = b.decidedBy ? `由${DECIDED_BY_LABEL[b.decidedBy]}决定` : undefined;
    return { state: 'final', label: OUTCOME_LABEL[b.outcome], tone, note };
  }
  if (local.phase === 'decided') {
    const tone = local.outcome === 'allowed-once' ? 'ok' : local.outcome === 'rejected' ? 'bad' : 'neutral';
    return { state: 'final', label: OUTCOME_LABEL[local.outcome], tone };
  }
  if (local.phase === 'conflict') return { state: 'final', label: '已被处理', tone: 'neutral' };
  if (local.phase === 'gone') return { state: 'final', label: '已过期', tone: 'neutral' };
  if (msLeft <= 0) return { state: 'final', label: '已超时，按拒绝处理', tone: 'bad' };
  return { state: 'actionable' };
}

/** 高风险工具审批卡片：工具名 / 原因 / 参数预览（可折叠，最多约 8 行）/ 倒计时 / 允许本次 · 拒绝。 */
export default function ApprovalCard({ b, taskId }: { b: ApprovalCardData; taskId: string | null }) {
  const [local, setLocal] = useState<LocalState>({ phase: 'idle' });
  const [msLeft, setMsLeft] = useState(() => remainingMs(b.expiresAt));
  const [argsOpen, setArgsOpen] = useState<boolean | null>(null);

  const resolved = resolve(b, local, msLeft);
  const actionable = resolved.state === 'actionable';
  const inFlight = local.phase === 'pending';

  // 倒计时：每秒刷新；已有最终结果或归零后停止。
  useEffect(() => {
    if (!actionable) return;
    const tick = () => setMsLeft(remainingMs(b.expiresAt));
    tick();
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [b.expiresAt, actionable]);

  const decide = async (decision: TerminalApprovalDecision) => {
    if (!taskId || inFlight || !actionable) return;
    setLocal({ phase: 'pending', decision });
    try {
      const res = await terminal.decideApproval(taskId, b.approvalId, decision);
      const outcome: TerminalApprovalOutcome = res?.outcome ?? (decision === 'allow' ? 'allowed-once' : 'rejected');
      setLocal({ phase: 'decided', outcome });
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) { setLocal({ phase: 'conflict' }); return; }
      if (e instanceof ApiError && e.status === 404) { setLocal({ phase: 'gone' }); return; }
      // 其他错误（网络 / 5xx）：留在可操作态，允许重试。
      setLocal({ phase: 'error', message: (e as Error).message || '提交失败' });
    }
  };

  const showArgs = argsOpen ?? actionable;   // 待决时默认展开参数，决定后默认收起
  const hasArgs = !!b.argumentsPreview && b.argumentsPreview.trim().length > 0;
  const urgent = actionable && msLeft <= 30_000;

  const accent = actionable ? COLORS.amber : resolved.tone === 'ok' ? COLORS.green : resolved.tone === 'bad' ? COLORS.red : COLORS.gray;
  const headerIcon = actionable
    ? <ExclamationCircleOutlined style={{ color: COLORS.amber }} />
    : resolved.tone === 'ok'
      ? <CheckCircleOutlined style={{ color: COLORS.green }} />
      : resolved.tone === 'bad'
        ? <CloseCircleOutlined style={{ color: COLORS.red }} />
        : <ClockCircleOutlined style={{ color: COLORS.gray }} />;

  return (
    <div
      data-approval-id={b.approvalId}
      style={{
        border: `1px solid ${actionable ? COLORS.amberBorder : COLORS.border}`,
        borderLeft: `3px solid ${accent}`,
        borderRadius: 8,
        background: actionable ? COLORS.amberBg : COLORS.cardBg,
        marginBottom: 8,
        fontSize: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', flexWrap: 'wrap' }}>
        {headerIcon}
        <SafetyOutlined style={{ color: COLORS.primary }} />
        <span style={{ fontWeight: 500, color: COLORS.text }}>高风险操作需要你确认</span>
        <code style={{ fontFamily: "'SF Mono', 'Fira Code', 'Menlo', monospace", fontSize: 11.5, color: COLORS.text, background: '#fff', border: `1px solid ${COLORS.border}`, borderRadius: 4, padding: '0 5px' }}>
          {b.tool || '(工具)'}
        </code>
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {actionable ? (
            <span style={{ color: urgent ? COLORS.red : COLORS.amber, fontVariantNumeric: 'tabular-nums' }} title={`到期时间 ${b.expiresAt}`}>
              <ClockCircleOutlined style={{ marginRight: 4 }} />
              {formatCountdown(msLeft)}
            </span>
          ) : (
            <Tag
              color={resolved.tone === 'ok' ? 'success' : resolved.tone === 'bad' ? 'error' : 'default'}
              style={{ marginInlineEnd: 0, fontSize: 11 }}
            >
              {resolved.label}
            </Tag>
          )}
        </span>
      </div>

      <div style={{ padding: '0 10px 10px' }}>
        {b.reason && (
          <div style={{ color: COLORS.text, lineHeight: 1.6 }}>
            <span style={{ color: COLORS.muted }}>原因：</span>{b.reason}
          </div>
        )}
        {!actionable && resolved.state === 'final' && resolved.note && (
          <div style={{ color: COLORS.muted, marginTop: 2 }}>{resolved.note}</div>
        )}

        {hasArgs && (
          <div style={{ marginTop: 6 }}>
            <span
              onClick={() => setArgsOpen(!showArgs)}
              style={{ color: COLORS.gray, cursor: 'pointer', userSelect: 'none' }}
            >
              {showArgs ? '收起参数' : '查看参数'}{' '}
              <DownOutlined style={{ fontSize: 9, transform: showArgs ? 'rotate(180deg)' : 'none' }} />
            </span>
            {showArgs && (
              // 约 8 行：12px × 1.55 行高 × 8 + 上下 padding
              <pre className="wb-pre" style={{ maxHeight: 170, overflow: 'auto' }}>{b.argumentsPreview}</pre>
            )}
          </div>
        )}

        {actionable && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
            <Button
              type="primary"
              size="small"
              icon={inFlight && local.decision === 'allow' ? <LoadingOutlined /> : <CheckCircleOutlined />}
              disabled={inFlight || !taskId}
              onClick={() => decide('allow')}
            >
              允许本次
            </Button>
            <Button
              size="small"
              danger
              icon={inFlight && local.decision === 'reject' ? <LoadingOutlined /> : <CloseCircleOutlined />}
              disabled={inFlight || !taskId}
              onClick={() => decide('reject')}
            >
              拒绝
            </Button>
            <span style={{ color: COLORS.muted }}>
              {inFlight ? '提交中…' : '不处理将在倒计时结束后按拒绝处理'}
            </span>
            {local.phase === 'error' && (
              <span style={{ color: COLORS.red }}>提交失败：{local.message}，可重试</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
