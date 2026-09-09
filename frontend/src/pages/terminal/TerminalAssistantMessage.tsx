import { useEffect, useState, type ReactNode } from 'react';
import {
  Button, Input, Popover, Select, Spin, Tag, Tooltip, Typography, message,
} from 'antd';
import {
  AudioOutlined, CheckCircleOutlined, CloseOutlined, DatabaseOutlined,
  DownloadOutlined, DownOutlined, EyeOutlined, FileTextOutlined, LoadingOutlined,
  PictureOutlined, RightOutlined, SafetyOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { multimodal, terminal, type TerminalTaskMessage, type VoiceProfile } from '../../api/client';
import ApprovalCard from '../../components/terminal/ApprovalCard';
import BrandLogoSlot, { BRAND_LOGO_SLOTS } from '../../branding/BrandLogoSlot';
import { presentAssistantMarkdown } from '../../utils/workspacePresentation';
import { workspaceInternalPath } from '../../utils/workspaceFileLinks';
import type {
  ArtifactOutput, Block, ChatFileLink, ChatMsg, TraceCategory,
} from './terminalConversationTypes';

const WB = {
  primary: '#6366F1',
  border: '#E5E7EB',
  botMsg: '#FFFFFF',
};

function messageTimeParts(value?: string): { label: string; title: string } | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;

  const now = new Date();
  const sameDay = date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
  const sameYear = date.getFullYear() === now.getFullYear();
  const time = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
  const label = sameDay
    ? time
    : `${sameYear ? '' : `${date.getFullYear()}-`}${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${time}`;
  const title = new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date);
  return { label, title };
}

export function MessageTimestamp({ value }: { value?: string }) {
  const formatted = messageTimeParts(value);
  if (!formatted) return null;
  return (
    <time
      dateTime={value}
      title={formatted.title}
      style={{ fontSize: 11, color: '#9ca3af', fontWeight: 400, fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }}
    >
      {formatted.label}
    </time>
  );
}

// ── 助手气泡：Claude Code 风格执行过程时间线 ──────────────────────────────

type ExecutionVerification = NonNullable<TerminalTaskMessage['execution_verification']>;

function verificationFromBlocks(blocks?: Block[]): ExecutionVerification | null {
  const calls = (blocks ?? []).filter((block): block is Extract<Block, { kind: 'tool_call' }> => block.kind === 'tool_call' && !block.running && !!block.result);
  if (!calls.length) return null;
  const succeeded = calls.filter((call) => call.result?.ok !== false).length;
  const failed = calls.length - succeeded;
  let lastFailedIndex = -1;
  calls.forEach((call, index) => { if (call.result?.ok === false) lastFailedIndex = index; });
  const recovered = failed > 0
    && extractArtifacts(blocks).length > 0
    && calls.slice(lastFailedIndex + 1).some((call) => call.result?.ok !== false);
  return {
    status: failed === 0 ? 'verified' : recovered ? 'recovered' : succeeded ? 'partial' : 'failed',
    tool_calls: calls.length,
    succeeded,
    failed,
  };
}

function ExecutionStatus({ verification, streaming }: { verification: ExecutionVerification | null; streaming: boolean }) {
  if (streaming) return <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 8, color: WB.primary }}><LoadingOutlined /> 执行中…</div>;
  if (!verification) return null;
  const display = {
    verified: { color: '#16a34a', label: '已验证执行', icon: <CheckCircleOutlined /> },
    recovered: { color: '#16a34a', label: '已完成（有重试）', icon: <CheckCircleOutlined /> },
    partial: { color: '#d97706', label: '部分完成', icon: <CheckCircleOutlined /> },
    failed: { color: '#dc2626', label: '执行失败', icon: <CloseOutlined /> },
    legacy_unverified: { color: '#d97706', label: '历史结果未验证', icon: <CloseOutlined /> },
  }[verification.status];
  return (
    <Tooltip title={verification.status === 'legacy_unverified' ? '未找到真实工具执行记录' : `工具调用 ${verification.tool_calls} 次：成功 ${verification.succeeded}，失败 ${verification.failed}`}>
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, marginBottom: 8, color: display.color }}>
        {display.icon} {display.label}
      </div>
    </Tooltip>
  );
}

function SpeechPlaybackButton({ text, disabled }: { text: string; disabled?: boolean }) {
  const [loading, setLoading] = useState(false);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [voiceId, setVoiceId] = useState<string>();
  const [style, setStyle] = useState('');
  const [speed, setSpeed] = useState(1);

  const openSettings = async () => {
    if (disabled || !text.trim()) return;
    setOpen(true);
    if (voices.length || voiceLoading) return;
    setVoiceLoading(true);
    try {
      const available = await multimodal.voices();
      setVoices(available);
      setVoiceId(available[0]?.id);
      if (!available.length) message.warning('管理员尚未为你分配可用音色');
    } catch (error) {
      message.error((error as Error).message || '音色加载失败');
    } finally {
      setVoiceLoading(false);
    }
  };

  const play = async () => {
    const content = text.trim();
    if (!content || disabled || loading) return;
    if (!voiceId) {
      message.warning('请选择一个可用音色');
      return;
    }
    setLoading(true);
    try {
      const created = await multimodal.speech({
        text: content.slice(0, 20_000),
        voice_profile_id: voiceId,
        style: style.trim() || undefined,
        speed,
        format: 'wav',
      });
      for (let attempt = 0; attempt < 150; attempt += 1) {
        const job = await multimodal.job(created.job_id);
        if (job.status === 'succeeded') {
          if (!job.output_url) throw new Error('朗读文件尚未生成播放地址');
          await new window.Audio(job.output_url).play();
          setOpen(false);
          return;
        }
        if (job.status === 'failed' || job.status === 'cancelled') {
          throw new Error(job.error_detail || job.error_category || '朗读生成失败');
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      throw new Error('朗读生成等待超过 5 分钟，可稍后重试');
    } catch (error) {
      message.error((error as Error).message || '朗读失败');
    } finally {
      setLoading(false);
    }
  };
  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={(next) => { if (!next) setOpen(false); else void openSettings(); }}
      content={<div style={{ width: 280, display: 'grid', gap: 10 }}>
        <Typography.Text strong>朗读设置</Typography.Text>
        <Select
          loading={voiceLoading}
          value={voiceId}
          onChange={setVoiceId}
          placeholder="选择企业授权音色"
          options={voices.map(voice => ({ value: voice.id, label: `${voice.name} · ${voice.voice_type}` }))}
        />
        <Input value={style} onChange={event => setStyle(event.target.value)} placeholder="可选：温和、正式、充满活力……" maxLength={500} />
        <Select value={speed} onChange={setSpeed} options={[
          { value: 0.75, label: '慢速 0.75×' },
          { value: 1, label: '正常 1.0×' },
          { value: 1.25, label: '较快 1.25×' },
          { value: 1.5, label: '快速 1.5×' },
        ]} />
        <Button type="primary" icon={loading ? <LoadingOutlined /> : <AudioOutlined />} loading={loading} disabled={!voiceId} onClick={() => void play()}>
          生成并播放
        </Button>
      </div>}
    >
      <Button
        type="text"
        size="small"
        icon={loading ? <LoadingOutlined /> : <AudioOutlined />}
        disabled={disabled || !text.trim()}
        style={{ marginTop: 8, paddingInline: 4, color: '#6b7280' }}
      >
        {loading ? '生成朗读中' : '朗读'}
      </Button>
    </Popover>
  );
}

export function AssistantBubble({ msg, streaming, onLink, fileLinks, taskId }: { msg: ChatMsg; streaming: boolean; onLink: (href: string) => void; fileLinks: ChatFileLink[]; taskId: string | null }) {
  const blocks = msg.blocks;
  const hasLiveBlocks = blocks && blocks.length > 0;
  const verification = msg.executionVerification ?? verificationFromBlocks(blocks);
  const structuredArtifacts = msg.artifacts ?? [];
  // 兜底：无 blocks（历史回放）直接渲染 content markdown
  if (!hasLiveBlocks) {
    return (
      <div style={{ maxWidth: '92%' }}>
        <AvatarHeader createdAt={msg.createdAt} />
        <div style={{ background: WB.botMsg, border: `1px solid ${WB.border}`, borderRadius: '16px 16px 16px 4px', boxShadow: '0 1px 2px rgba(0,0,0,0.04)', padding: 16 }}>
          <ExecutionStatus verification={verification} streaming={streaming} />
          <div className="wb-md">
            <Md onLink={onLink} files={fileLinks} hideLegacyArtifactTable={structuredArtifacts.length > 0}>
              {msg.content || '(无内容)'}
            </Md>
          </div>
          <ArtifactGallery artifacts={structuredArtifacts} fileLinks={fileLinks} streaming={streaming} onLink={onLink} />
          <SpeechPlaybackButton text={msg.content} disabled={streaming} />
        </div>
      </div>
    );
  }

  const lastBlock = blocks![blocks!.length - 1];
  const thinking = streaming && (lastBlock.kind === 'phase' || (lastBlock.kind === 'tool_call' && lastBlock.running));
  const artifacts = structuredArtifacts.length ? structuredArtifacts : extractArtifacts(blocks);
  const artifactPaths = new Set(artifacts.map((artifact) => artifact.path).filter(Boolean));
  const legacyChanges = extractFileChanges(blocks).filter((file) => !artifactPaths.has(file.path));
  const spokenText = msg.content || blocks
    .filter((block): block is Extract<Block, { kind: 'text' }> => block.kind === 'text')
    .map((block) => block.content)
    .join('\n');

  return (
    <div style={{ maxWidth: '92%' }}>
      <AvatarHeader streaming={streaming} createdAt={msg.createdAt} />
      <div style={{ background: WB.botMsg, border: `1px solid ${WB.border}`, borderRadius: '16px 16px 16px 4px', boxShadow: '0 1px 2px rgba(0,0,0,0.04)', padding: 16 }}>
        <ExecutionStatus verification={verification} streaming={streaming} />

        {/* 时间线 blocks */}
        {blocks!.map((b, i) => {
          if (b.kind === 'phase') {
            const isCurrent = streaming && i === blocks!.length - 1;
            return (
              <div key={i} className="wb-phase">
                {isCurrent ? <LoadingOutlined /> : <RightOutlined style={{ fontSize: 10 }} />}
                <span>{isCurrent ? '思考中…' : `第 ${b.index + 1} 步`}</span>
              </div>
            );
          }
          if (b.kind === 'tool_call') {
            return <ToolCard key={i} b={b} />;
          }
          if (b.kind === 'trace') {
            return <TraceChip key={i} b={b} />;
          }
          if (b.kind === 'approval') {
            return <ApprovalCard key={`approval:${b.approvalId}`} b={b} taskId={taskId} />;
          }
          if (b.kind === 'text') {
            const isLast = i === blocks!.length - 1;
            const showCursor = streaming && isLast;
            return (
              <div key={i} className="wb-md" style={{ marginTop: 4 }}>
                <Md onLink={onLink} files={fileLinks} hideLegacyArtifactTable={artifacts.length > 0}>{b.content}</Md>
                {showCursor && <span className="wb-cursor" />}
              </div>
            );
          }
          // meta（记忆沉淀）
          if (b.kind === 'meta') {
            const data = b.data as Record<string, unknown>;
            const label = `记忆沉淀 · ${(data?.extracted as number) ?? 0} 条`;
            return (
              <div key={i} className="wb-meta">
                <DatabaseOutlined /> {label}
              </div>
            );
          }
          return null;
        })}
        {thinking && (
          <div className="wb-phase" style={{ color: WB.primary }}>
            <LoadingOutlined /> 智能体工作中…
          </div>
        )}
        <ArtifactGallery
          artifacts={artifacts}
          fileLinks={fileLinks}
          streaming={streaming}
          onLink={onLink}
        />
        <ChangesBox files={legacyChanges} fileLinks={fileLinks} onLink={onLink} />
        <SpeechPlaybackButton text={spokenText} disabled={streaming} />
      </div>
    </div>
  );
}

function extractArtifacts(blocks?: Block[]): ArtifactOutput[] {
  if (!blocks) return [];
  const ordered: ArtifactOutput[] = [];
  const deletedPaths = new Set<string>();
  for (const block of blocks) {
    if (block.kind !== 'tool_call' || block.running || block.result?.ok === false) continue;
    if (block.name === 'workspace_delete_file') {
      try {
        const args = JSON.parse(block.arguments || '{}') as { path?: unknown };
        if (typeof args.path === 'string' && args.path) deletedPaths.add(args.path);
      } catch { /* invalid tool arguments are already visible in the trace */ }
      continue;
    }
    if (!FILE_WRITE_TOOLS.has(block.name)) continue;
    const rawOutputs = artifactRecords(block.result?.content || '');
    for (const raw of rawOutputs) {
      const output = raw;
      const fileId = typeof output.file_id === 'string'
        ? output.file_id
        : (typeof output.fileId === 'string' ? output.fileId : '');
      const path = typeof output.path === 'string' ? output.path : '';
      if (!fileId && !path) continue;
      const name = typeof output.display_name === 'string' && output.display_name
        ? output.display_name
        : (typeof output.name === 'string' && output.name
            ? output.name
            : (typeof output.filename === 'string' && output.filename
                ? output.filename
                : (path.split('/').pop() || '生成文件')));
      ordered.push({
        fileId,
        path,
        name,
        mimeType: typeof output.mime_type === 'string'
          ? output.mime_type
          : (typeof output.content_type === 'string' ? output.content_type : ''),
        size: typeof output.size === 'number'
          ? output.size
          : (typeof output.size_bytes === 'number' ? output.size_bytes : undefined),
        width: typeof output.width === 'number' ? output.width : undefined,
        height: typeof output.height === 'number' ? output.height : undefined,
        parseStatus: typeof output.parse_status === 'string' ? output.parse_status : undefined,
      });
    }
  }
  const seen = new Set<string>();
  const deduped: ArtifactOutput[] = [];
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const artifact = ordered[index];
    const key = artifact.fileId || artifact.path;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    deduped.unshift(artifact);
  }
  return deduped.filter((artifact) => !artifact.path || !deletedPaths.has(artifact.path));
}

/** 历史工具与平台文件工具的结果包装层略有不同。这里仅在文件写工具内
 *  递归解包已知字段，兼容 outputs/files/artifacts 以及 JSON 字符串嵌套。 */
function artifactRecords(content: string): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [];
  const visit = (value: unknown, depth: number) => {
    if (depth > 5 || value === null || value === undefined) return;
    if (typeof value === 'string') {
      const trimmed = value.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '');
      if (!trimmed || (!trimmed.startsWith('{') && !trimmed.startsWith('['))) return;
      try { visit(JSON.parse(trimmed), depth + 1); } catch { /* textual result */ }
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, depth + 1));
      return;
    }
    if (typeof value !== 'object') return;
    const item = value as Record<string, unknown>;
    if (item.file_id || item.fileId || item.path) records.push(item);
    for (const key of ['outputs', 'files', 'artifacts', 'output', 'data', 'result', 'content']) {
      if (key in item) visit(item[key], depth + 1);
    }
  };
  visit(content, 0);
  return records;
}

function ArtifactGallery({
  artifacts, fileLinks, streaming, onLink,
}: {
  artifacts: ArtifactOutput[];
  fileLinks: ChatFileLink[];
  streaming: boolean;
  onLink: (href: string) => void;
}) {
  if (!artifacts.length) return null;
  return (
    <section style={{ marginTop: 12 }} aria-label="本轮交付文件">
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 8, color: '#374151', fontSize: 12, fontWeight: 600 }}>
        <CheckCircleOutlined style={{ color: '#16a34a' }} />
        本轮交付
        <Tag color="green" style={{ margin: 0, fontSize: 10, lineHeight: '18px' }}>{artifacts.length}</Tag>
      </div>
      <div style={{ display: 'grid', gap: 10 }}>
        {artifacts.map((artifact) => (
          <InlineArtifactCard
            key={artifact.fileId || artifact.path}
            artifact={artifact}
            fileLinks={fileLinks}
            streaming={streaming}
            onLink={onLink}
          />
        ))}
      </div>
    </section>
  );
}

const CHAT_IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'avif']);

function artifactExtension(name: string): string {
  const index = name.lastIndexOf('.');
  return index >= 0 ? name.slice(index + 1).toLowerCase() : '';
}

function formatArtifactSize(size?: number): string {
  if (size === undefined || !Number.isFinite(size)) return '';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size < 10 * 1024 ? 1 : 0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function InlineArtifactCard({
  artifact, fileLinks, streaming, onLink,
}: {
  artifact: ArtifactOutput;
  fileLinks: ChatFileLink[];
  streaming: boolean;
  onLink: (href: string) => void;
}) {
  const resolved = fileLinks.find((file) => (
    (!!artifact.fileId && file.id === artifact.fileId) || (!!artifact.path && file.path === artifact.path)
  ));
  const fileId = artifact.fileId || resolved?.id || '';
  const path = artifact.path || resolved?.path || '';
  const name = artifact.name || resolved?.originalName || resolved?.name || path.split('/').pop() || '生成文件';
  const mimeType = artifact.mimeType || resolved?.mimeType || '';
  const size = artifact.size ?? resolved?.size;
  const extension = artifactExtension(name);
  const isImage = mimeType.startsWith('image/') || CHAT_IMAGE_EXTENSIONS.has(extension);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    if (!isImage || !fileId || streaming) return;
    let cancelled = false;
    let objectUrl = '';
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 20000);
    setImageUrl(null);
    setImageLoading(true);
    setImageError(null);
    terminal.getWsFileOriginalPreview(fileId, controller.signal)
      .catch((previewError) => {
        if (controller.signal.aborted) throw previewError;
        // 原文件预览可能被部署级开关关闭；图片卡片仍应能走已有下载链路展示。
        return terminal.downloadWsFile(fileId, controller.signal);
      })
      .then((blob) => {
        if (cancelled) return;
        if (!blob.size) throw new Error('图片文件为空');
        objectUrl = URL.createObjectURL(blob);
        setImageUrl(objectUrl);
      })
      .catch((reason) => {
        if (!cancelled) {
          setImageError(controller.signal.aborted ? '图片读取超时，请重试' : ((reason as Error)?.message || '图片读取失败'));
        }
      })
      .finally(() => {
        window.clearTimeout(timeout);
        if (!cancelled) setImageLoading(false);
      });
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeout);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [fileId, isImage, reloadToken, streaming, resolved?.updatedAt]);

  const openPreview = () => {
    if (fileId) onLink(workspaceInternalPath(fileId));
    else if (path) onLink(path);
    else message.warning('文件路径尚未保存，请稍后重试');
  };

  const download = async () => {
    if (!fileId) {
      message.warning('文件尚未保存，暂时无法下载');
      return;
    }
    try {
      const blob = await terminal.downloadWsFile(fileId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = name;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (reason) {
      message.error((reason as Error)?.message || '下载失败');
    }
  };

  if (isImage) {
    return (
      <article style={{ width: 'min(480px, 100%)', overflow: 'hidden', border: '1px solid #dfe3ee', borderRadius: 12, background: '#fff', boxShadow: '0 1px 3px rgba(15,23,42,0.06)' }}>
        <div
          role="button"
          tabIndex={fileId || path ? 0 : -1}
          onClick={openPreview}
          onKeyDown={(event) => {
            if ((!fileId && !path) || (event.key !== 'Enter' && event.key !== ' ')) return;
            event.preventDefault();
            openPreview();
          }}
          style={{ display: 'block', width: '100%', minHeight: 180, maxHeight: 420, padding: 0, border: 0, background: '#f3f4f6', cursor: fileId || path ? 'zoom-in' : 'default', overflow: 'hidden' }}
        >
          {streaming ? (
            <div style={{ height: 220, display: 'grid', placeItems: 'center', color: '#6b7280', fontSize: 12 }}><Spin size="small" /> 正在保存图片…</div>
          ) : imageLoading ? (
            <div style={{ height: 220, display: 'grid', placeItems: 'center' }}><Spin /></div>
          ) : imageUrl ? (
            <img src={imageUrl} alt={name} style={{ display: 'block', width: '100%', maxHeight: 420, objectFit: 'contain', background: '#f8fafc' }} />
          ) : (
            <div style={{ height: 220, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 10, color: '#6b7280' }}>
              <PictureOutlined style={{ fontSize: 34, color: '#94a3b8' }} />
              <span style={{ fontSize: 12 }}>{imageError || '图片暂时无法读取'}</span>
              {!!fileId && <Button size="small" onClick={(event) => { event.stopPropagation(); setReloadToken((value) => value + 1); }}>重试</Button>}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '10px 11px' }}>
          <PictureOutlined style={{ color: '#7c3aed', fontSize: 18 }} />
          <div style={{ minWidth: 0, flex: 1 }}>
            <div title={name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#1f2937', fontSize: 13, fontWeight: 550 }}>{name}</div>
            <div style={{ color: '#9ca3af', fontSize: 10, marginTop: 2 }}>
              {[artifact.width && artifact.height ? `${artifact.width}×${artifact.height}` : '', formatArtifactSize(size)].filter(Boolean).join(' · ') || '图片'}
            </div>
          </div>
          <Tooltip title="打开完整预览"><Button type="text" size="small" icon={<EyeOutlined />} onClick={openPreview} /></Tooltip>
          <Tooltip title="下载原文件"><Button type="text" size="small" icon={<DownloadOutlined />} onClick={() => void download()} /></Tooltip>
        </div>
      </article>
    );
  }

  return (
    <article style={{ display: 'flex', alignItems: 'center', gap: 11, width: 'min(520px, 100%)', padding: '11px 12px', border: '1px solid #dfe3ee', borderRadius: 11, background: '#fff', boxShadow: '0 1px 3px rgba(15,23,42,0.05)' }}>
      <div style={{ width: 40, height: 44, display: 'grid', placeItems: 'center', borderRadius: 9, background: '#eef2ff', color: WB.primary, flex: '0 0 auto' }}>
        <FileTextOutlined style={{ fontSize: 21 }} />
      </div>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div title={name} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#1f2937', fontSize: 13, fontWeight: 550 }}>{name}</div>
        <div style={{ color: '#9ca3af', fontSize: 10, marginTop: 4 }}>
          {[extension ? extension.toUpperCase() : '文件', formatArtifactSize(size), artifact.parseStatus === 'ready' || resolved?.parseStatus === 'ready' ? 'AI 已解析' : '', artifact.sourceLabel || ''].filter(Boolean).join(' · ')}
        </div>
      </div>
      <Button size="small" icon={<EyeOutlined />} onClick={openPreview}>预览</Button>
      <Tooltip title="下载原文件"><Button type="text" size="small" icon={<DownloadOutlined />} onClick={() => void download()} /></Tooltip>
    </article>
  );
}

// ── 本轮文件变更汇总 ──────────────────────────────────────────────────────
// 从 blocks 里筛出 workspace_write_file / generate_docx 两类已成功完成的 tool_call，
// 解析 arguments 取路径/文件名，作为本轮「新生成与修改」的文件清单。
// 实时走 tool_call 事件、历史回放由 tracesToBlocks 还原成同样的 tool_call block，两条路径在此统一。
const FILE_WRITE_TOOLS = new Set([
  'workspace_write_file', 'generate_docx', 'spreadsheet_tool', 'document_tool',
  'presentation_tool', 'pdf_tool', 'text_tool', 'image_tool', 'archive_tool',
  'spreadsheet_create', 'spreadsheet_edit', 'spreadsheet_convert',
  'document_create', 'document_edit', 'document_convert',
  'presentation_create', 'presentation_edit', 'presentation_convert',
  'pdf_create', 'pdf_merge', 'pdf_split', 'pdf_extract', 'pdf_convert',
  'text_create', 'text_edit', 'text_convert', 'business_export_to_workspace_file',
  'image_generation_tool',
]);

function extractFileChanges(blocks?: Block[]): { path: string; generated: boolean }[] {
  if (!blocks) return [];
  const ordered: { path: string; generated: boolean }[] = [];
  const deletedPaths = new Set<string>();
  for (const b of blocks) {
    if (b.kind !== 'tool_call') continue;
    if (b.running || b.result?.ok === false) continue;
    if (b.name === 'workspace_delete_file') {
      try {
        const args = JSON.parse(b.arguments || '{}') as { path?: unknown };
        if (typeof args.path === 'string' && args.path) deletedPaths.add(args.path);
      } catch { /* invalid tool arguments are already visible in the trace */ }
      continue;
    }
    if (!FILE_WRITE_TOOLS.has(b.name)) continue;
    try {
      const result = JSON.parse(b.result?.content || '{}') as { outputs?: { path?: string }[] };
      for (const output of result.outputs ?? []) {
        if (output.path) ordered.push({ path: output.path, generated: true });
      }
      if ((result.outputs?.length ?? 0) > 0) continue;
    } catch { /* legacy textual tool result */ }
    let path = '';
    try {
      const p = JSON.parse(b.arguments || '{}');
      path = b.name === 'generate_docx' ? String(p.filename ?? '') : String(p.path ?? '');
    } catch { /* keep empty */ }
    if (!path) continue;
    ordered.push({ path, generated: b.name === 'generate_docx' });
  }
  // 同一路径多次写入只保留最后一次（去重，保持出现顺序）
  const seen = new Set<string>();
  const dedup: { path: string; generated: boolean }[] = [];
  for (let i = ordered.length - 1; i >= 0; i--) {
    if (seen.has(ordered[i].path)) continue;
    seen.add(ordered[i].path);
    dedup.unshift(ordered[i]);
  }
  return dedup.filter((file) => !deletedPaths.has(file.path));
}

function ChangesBox({ files, fileLinks, onLink }: { files: { path: string; generated: boolean }[]; fileLinks: ChatFileLink[]; onLink: (href: string) => void }) {
  const [open, setOpen] = useState(false);
  if (!files.length) return null;
  return (
    <div style={{ border: `1px solid ${WB.border}`, borderRadius: 8, background: '#FAFBFC', marginTop: 10 }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12 }}
      >
        <FileTextOutlined style={{ color: WB.primary }} />
        <span style={{ fontWeight: 500, color: '#1f2937' }}>查看所有变更</span>
        <Tag color="blue" style={{ marginInlineStart: 0, fontSize: 11, padding: '0 6px' }}>{files.length}</Tag>
        <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
          {open ? '收起' : '展开'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
        </span>
      </div>
      {open && (
        <div style={{ padding: '4px 10px 10px', borderTop: `1px solid ${WB.border}` }}>
          {files.map((f, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', fontSize: 12 }}>
              {f.generated
                ? <FileTextOutlined style={{ color: '#0ea5e9' }} />
                : <CheckCircleOutlined style={{ color: '#22c55e' }} />}
              <a
                onClick={(e) => {
                  e.preventDefault();
                  const resolved = fileLinks.find((item) => item.path === f.path);
                  onLink(resolved ? workspaceInternalPath(resolved.id) : f.path);
                }}
                style={{ color: WB.primary, cursor: 'pointer', wordBreak: 'break-all' }}
              >{f.path.replace(/^(?:技能输出|平台工具输出)\/[0-9a-f-]{36}\//i, '').replace(/^\d{8}-\d{6}-[0-9a-f]{8}-/i, '')}</a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AvatarHeader({ streaming, createdAt }: { streaming?: boolean; createdAt?: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
      <BrandLogoSlot slot={BRAND_LOGO_SLOTS.assistantAvatar} width={28} height={28} />
      <span style={{ fontSize: 14, fontWeight: 500, color: '#1f2937' }}>灼见</span>
      {streaming && <Tag color="processing" style={{ marginInlineStart: 4, fontSize: 11 }}>live</Tag>}
      <MessageTimestamp value={createdAt} />
    </div>
  );
}

// ── 工具调用卡片 ─────────────────────────────────────────────────────────

function ToolCard({ b }: { b: Extract<Block, { kind: 'tool_call' }> }) {
  const [open, setOpen] = useState(false);
  let prettyArgs = b.arguments;
  try {
    if (b.arguments && b.arguments.trim()) {
      prettyArgs = JSON.stringify(JSON.parse(b.arguments), null, 2);
    }
  } catch { /* keep raw */ }

  const ok = b.result?.ok;
  const statusColor = b.running ? WB.primary : (ok === false ? '#ef4444' : '#22c55e');
  const statusText = b.running ? '调用中…' : (ok === false ? '失败' : '完成');

  return (
    <div style={{ border: `1px solid ${WB.border}`, borderRadius: 8, background: '#FAFBFC', marginBottom: 8 }}>
      <div
        onClick={() => setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12 }}
      >
        {b.running
          ? <LoadingOutlined style={{ color: statusColor }} />
          : (ok === false
              ? <CloseOutlined style={{ color: statusColor }} />
              : <CheckCircleOutlined style={{ color: statusColor }} />)}
        <ThunderboltOutlined style={{ color: WB.primary }} />
        <span style={{ fontWeight: 500, color: '#1f2937' }}>{b.name || '(工具)'}</span>
        <span style={{ color: statusColor }}>{statusText}</span>
        <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
          {open ? '收起' : '详情'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
        </span>
      </div>
      {open && (
        <div style={{ padding: '0 10px 10px', borderTop: `1px solid ${WB.border}` }}>
          {prettyArgs && (
            <>
              <div style={{ color: '#6b7280', marginTop: 8, marginBottom: 2 }}>参数</div>
              <pre className="wb-pre">{prettyArgs}</pre>
            </>
          )}
          {b.result && (
            <>
              <div style={{ color: '#6b7280', marginTop: 8, marginBottom: 2 }}>
                结果{ok === false && <span style={{ color: '#ef4444' }}>（失败）</span>}
              </div>
              <pre className="wb-pre" style={{ color: ok === false ? '#fca5a5' : undefined }}>{b.result.content || '(空)'}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── 原生 Assistant Core 资源调用痕迹 ──────────────────────────────────
// 与正文和工具卡片区分：轻量单行 + 左侧主色竖条 + 类别图标，可展开看明细。

const TRACE_META: Record<TraceCategory, { icon: ReactNode; color: string; label: string }> = {
  memory: { icon: <DatabaseOutlined />, color: '#f59e0b', label: '记忆' },
  file: { icon: <FileTextOutlined />, color: '#0ea5e9', label: '文件' },
  policy: { icon: <SafetyOutlined />, color: '#f97316', label: '策略' },
};

function TraceChip({ b }: { b: Extract<Block, { kind: 'trace' }> }) {
  const [open, setOpen] = useState(false);
  const meta = TRACE_META[b.category] ?? TRACE_META.file;
  // 把 detail 里的数值字段拼成一行摘要（如 命中 3 条 / 注入 2 个），无则只显标题
  const d = (b.detail ?? {}) as Record<string, unknown>;
  const summaryBits: string[] = [];
  const pushNum = (key: string, label: string) => {
    if (typeof d[key] === 'number') summaryBits.push(`${label} ${d[key]}`);
  };
  pushNum('facts', '条');
  pushNum('history', '历史');
  pushNum('files', '文件');
  pushNum('systems', '系统');
  pushNum('interfaces', '接口');
  if (Array.isArray(d.names) && d.names.length) summaryBits.push(`${(d.names as unknown[]).length} 个`);
  if (Array.isArray(d.paths) && d.paths.length) summaryBits.push(`${(d.paths as unknown[]).length} 个`);
  const summary = summaryBits.join(' · ');
  const hasDetail = Object.keys(d).length > 0;
  return (
    <div className="wb-trace" style={{ borderLeftColor: meta.color }}>
      <div
        onClick={() => hasDetail && setOpen((o) => !o)}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 10px', cursor: hasDetail ? 'pointer' : 'default', fontSize: 12 }}
      >
        <span style={{ color: meta.color, display: 'inline-flex' }}>{meta.icon}</span>
        <span style={{ color: meta.color, fontWeight: 500, fontSize: 11 }}>{meta.label}</span>
        <span style={{ color: '#374151' }}>{b.title}</span>
        {summary && <span style={{ color: '#9ca3af' }}>· {summary}</span>}
        {hasDetail && (
          <span style={{ marginLeft: 'auto', color: '#9ca3af' }}>
            {open ? '收起' : '明细'} <DownOutlined style={{ fontSize: 9, transform: open ? 'rotate(180deg)' : 'none' }} />
          </span>
        )}
      </div>
      {open && hasDetail && (
        <div style={{ padding: '0 10px 8px', borderTop: `1px solid ${WB.border}` }}>
          <pre className="wb-pre" style={{ marginTop: 6 }}>{JSON.stringify(d, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

// ── Markdown 渲染 ────────────────────────────────────────────────────────

function Md({
  children, onLink, files, hideLegacyArtifactTable = false,
}: {
  children: string;
  onLink: (href: string) => void;
  files: ChatFileLink[];
  hideLegacyArtifactTable?: boolean;
}) {
  // 先把正文里裸出现的「工作空间文件名」自动包成 markdown 链接，再交给 ReactMarkdown 渲染
  const redacted = presentAssistantMarkdown(children, files.map((file) => ({
    id: file.id,
    path: file.path,
    original_filename: file.originalName,
  })), hideLegacyArtifactTable);
  const src = linkifyFiles(redacted, files);
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // 对话内容中的链接点击后不再新标签跳转，而是弹出右侧浏览器抽屉预览
        a: ({ node: _n, href, ...props }) => (
          <a
            {...props}
            href={href}
            onClick={(e) => { if (href) { e.preventDefault(); onLink(href); } }}
            style={{ color: WB.primary, cursor: 'pointer' }}
          />
        ),
      }}
    >
      {src}
    </ReactMarkdown>
  );
}

/** 把 markdown 正文中裸出现的工作空间文件名包成 [name](<path>) 链接。
 *  跳过代码块/行内代码/已有链接，避免破坏原有结构；用前后非 \w 边界降低误匹配。 */
function linkifyFiles(md: string, files: { id?: string; path: string; name: string }[]): string {
  if (!files.length) return md;
  const nameCounts = new Map<string, number>();
  for (const file of files) nameCounts.set(file.name, (nameCounts.get(file.name) ?? 0) + 1);
  const byName = new Map<string, string>();
  for (const f of files) {
    if (f.name && f.name.length >= 2 && nameCounts.get(f.name) === 1) {
      byName.set(f.name, f.id ? workspaceInternalPath(f.id) : f.path);
    }
  }
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  if (!names.length) return md;
  const nameAlt = names.map(escapeRegExp).join('|');
  // 先按 代码围栏 / 行内代码 / 已有链接 分段，只在纯文本段里做文件名替换
  const tokenRe = /(`{3,}[\s\S]*?`{3,})|(`[^`\n]+`)|(\[[^\]]*\]\([^)]*\))/g;
  const linkifyPlain = (text: string) =>
    text.replace(new RegExp(`(?<![\\w/])(${nameAlt})(?![\\w])`, 'g'), (m) => {
      const p = byName.get(m);
      return p ? `[${m}](<${p}>)` : m;
    });
  let out = '';
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = tokenRe.exec(md))) {
    out += linkifyPlain(md.slice(last, m.index));
    out += m[0];
    last = m.index + m[0].length;
  }
  out += linkifyPlain(md.slice(last));
  return out;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
