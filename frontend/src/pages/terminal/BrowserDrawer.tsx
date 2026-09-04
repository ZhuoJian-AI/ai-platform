import { useCallback, useEffect, useMemo, useRef, useState, type ClipboardEvent as ReactClipboardEvent, type CSSProperties, type ReactNode } from 'react';
import { Alert, Drawer, Tooltip, Spin, Empty, Typography, Button, Input, List, Modal, Select, message, Segmented, Tag } from 'antd';
import {
  ArrowLeftOutlined, ArrowRightOutlined, ReloadOutlined, SelectOutlined,
  FileTextOutlined, GlobalOutlined, FileWordOutlined, FilePdfOutlined,
  FileImageOutlined, DownloadOutlined, EditOutlined, LinkOutlined, SaveOutlined,
  ExportOutlined, FullscreenOutlined, FullscreenExitOutlined, SearchOutlined, HistoryOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import OriginalFilePreview, { supportsPagedWorkspacePreview } from '../../components/files/OriginalFilePreview';
import type {
  WorkspaceDownloadTicket, WorkspaceFallbackPreview, WorkspaceOriginalPreviewSource,
  WorkspacePdfPreviewInfo, WorkspacePreviewPreferredMode, WorkspacePreviewSession,
  WorkspaceSpreadsheetPage, WorkspaceSpreadsheetPreview, WorkspaceFile, WorkspaceFileCapabilities, WorkspaceFileEvent, WorkspaceFileVersion,
  WorkspaceOfficeEditStatus,
} from '../../api/client';
import { WorkspaceEditSessionView } from '../../components/files/WorkspacePreviewSessionView';
import { parseWorkspaceInternalUrl, workspaceFileLabel, workspaceInternalUrl } from '../../utils/workspaceFileLinks';
import { parseCsvDocument, serializeCsvDocument, type CsvDocument } from '../../utils/csvDocument';
import { workspaceOfficeEditOutcome } from '../../utils/workspaceOfficeEdit';
// mammoth 仅在打开 .docx 时按需动态加载（见下方 useEffect），不进主包。

/** WorkBuddy 配色（与 Terminal.tsx 保持一致）。 */
const WB = {
  primary: '#6366F1', primaryHover: '#818CF8',
  border: '#E5E7EB', hover: '#EEF0F7',
};

const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

// ── 浏览器抽屉中可渲染的"源" ──────────────────────────────────────────────
// 每个源都携带原始 href，供地址栏展示与刷新时重新解析。
type Source = (
  | { kind: 'web'; url: string; href: string }
  | { kind: 'pdf'; url: string; href: string }
  | { kind: 'docx'; url: string; href: string }
  | { kind: 'docx-bin'; content: string; path: string; href: string; fileId: string }
  | { kind: 'parsed'; content: string; originalContent: string; mime: string; path: string; href: string; fileId: string; parseKind: string | null }
  | { kind: 'binary'; content: string; mime: string; path: string; href: string; fileId: string; note: string }
  | { kind: 'image'; src: string; href: string; path?: string; fileId?: string }
  | { kind: 'md'; content: string; path: string; href: string; fileId: string }
  | { kind: 'html-text'; content: string; path: string; href: string; fileId: string }
  | { kind: 'text'; content: string; path: string; href: string; fileId: string }
  | { kind: 'unsupported'; href: string; url?: string; note?: string }
) & { file?: WorkspaceFile; versionId?: string };

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif']);
// 与后端显式编辑会话白名单保持一致；不把仅能预览的 ODF 文件误标为“可编辑”。
const OFFICE_EDIT_EXTS = new Set([
  'doc', 'docx', 'dot', 'wps', 'wpt', 'dotx', 'docm', 'dotm',
  'ppt', 'pptx', 'pptm', 'ppsx', 'ppsm', 'pps', 'potx', 'potm', 'dpt', 'dps',
  'et', 'xls', 'xlt', 'xlsx', 'xlsm', 'xltx', 'xltm',
]);
const OFFICE_EDIT_MAX_BYTES = 200 * 1024 * 1024;

function extOf(path: string): string {
  const i = path.lastIndexOf('.');
  return i >= 0 ? path.slice(i + 1).toLowerCase() : '';
}

function imgMimeOf(ext: string): string {
  const m: Record<string, string> = {
    png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
    webp: 'image/webp', svg: 'image/svg+xml', bmp: 'image/bmp', ico: 'image/x-icon',
    avif: 'image/avif',
  };
  return m[ext] || 'image/png';
}

/** 按 URL 扩展名把外部链接归类为网页 / PDF / Word / 图片。 */
function classifyUrl(url: string): Source {
  const ext = extOf(url.split('?')[0].split('#')[0]);
  if (ext === 'pdf') return { kind: 'pdf', url, href: url };
  if (ext === 'docx' || ext === 'doc') return { kind: 'docx', url, href: url };
  if (IMAGE_EXTS.has(ext)) return { kind: 'image', src: url, href: url };
  return { kind: 'web', url, href: url };
}

/** 把工作空间文件（content 为文本或 base64 二进制）归类为可渲染的 Source。
 *  统一分类逻辑：终端「工作空间管理」与「任务抽屉文件区」共用，消除两处差异。*/
export function classifyFile(f: WorkspaceFile): Source {
  const content = f.content ?? '';
  const ext = extOf(f.path);
  const meta = (f.metadata ?? {}) as { binary?: boolean; mime?: string };
  // 图片：二进制（base64）图片按 metadata.mime；无 metadata 时按扩展名兜底
  if (((meta.binary && (meta.mime || '').startsWith('image/')) || IMAGE_EXTS.has(ext)) && (!meta.binary || !!content)) {
    const mime = meta.mime || imgMimeOf(ext);
    return { kind: 'image', src: `data:${mime};base64,${content}`, href: f.path, path: f.path, fileId: f.id, file: f };
  }
  if (meta.binary && f.parse_status === 'ready' && f.extracted_text) {
    return {
      kind: 'parsed', content: f.extracted_text, originalContent: content,
      mime: meta.mime || 'application/octet-stream', path: f.path, href: f.path,
      fileId: f.id, parseKind: f.parse_kind ?? null, file: f,
    };
  }
  if (meta.binary) {
    return {
      kind: 'binary', content, mime: meta.mime || 'application/octet-stream',
      path: f.path, href: f.path, fileId: f.id,
      note: f.parse_error || '该文件尚未解析，可点击“重新解析”', file: f,
    };
  }
  if (ext === 'md' || ext === 'markdown') return { kind: 'md', content, path: f.path, href: f.path, fileId: f.id, file: f };
  // 二进制 .docx（base64 + metadata.binary）：客户端 mammoth 解析为 HTML 渲染，避免 base64 乱码。
  // .doc 旧格式 mammoth 不支持，仍走下面的 HTML/文本兜底。
  if (meta.binary && ext === 'docx') {
    return { kind: 'docx-bin', content, path: f.path, href: f.path, fileId: f.id, file: f };
  }
  // 工作空间文件是不可信输入。HTML（包括 Agent 生成的伪 .doc/.docx）只能作为
  // 纯文本展示，不得放入 srcDoc 或同源 text/html Blob 中执行。
  if (['html', 'htm', 'doc', 'docx'].includes(ext)) {
    return { kind: 'html-text', content, path: f.path, href: f.path, fileId: f.id, file: f };
  }
  return { kind: 'text', content, path: f.path, href: f.path, fileId: f.id, file: f };
}

/** Google Docs Viewer 渲染 Word（仅对公网 URL 有效）。 */
function gviewUrl(url: string): string {
  return `https://docs.google.com/gview?url=${encodeURIComponent(url)}&embedded=true`;
}

/** base64 → Uint8Array（atob 在浏览器同步可用）。 */
function b64ToUint8(b64: string): Uint8Array {
  const bin = atob(b64);
  const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  return u;
}

/** 把 mammoth 输出的 HTML 片段包成带基础排版的完整文档，供 iframe srcDoc 渲染。 */
function wrapDocxHtml(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
    color:#1f2937;line-height:1.6;padding:20px 28px;}
  h1,h2,h3{color:#111827;} table{border-collapse:collapse;} td,th{border:1px solid #d1d5db;padding:4px 8px;}
  img{max-width:100%;} a{color:#6366F1;}
  </style></head><body>${html}</body></html>`;
}

// ── 抽屉内 Markdown 渲染：内部链接在抽屉内继续导航，而非新标签跳转 ──────────
function MdNav({ content, onLink }: { content: string; onLink: (href: string) => void }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        table: ({ node: _n, ...props }) => (
          <div className="wb-md-table-wrap">
            <table {...props} />
          </div>
        ),
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
      {content}
    </ReactMarkdown>
  );
}

function displayNameFromPath(path: string): string {
  return (path.split('/').pop() || path)
    .replace(/^\d{8}-\d{6}-[0-9a-f]{8}-/i, '')
    .replace(/^\d{8}T\d{6}Z-[0-9a-f]{8}-/i, '');
}

interface ParsedSection {
  id: string;
  title: string;
  content: string;
}

function parsedSections(content: string): ParsedSection[] {
  const lines = content.split('\n');
  const sections: ParsedSection[] = [];
  let title = '文档开头';
  let buffer: string[] = [];
  const flush = () => {
    if (!buffer.length) return;
    sections.push({ id: `parsed-section-${sections.length}`, title, content: buffer.join('\n') });
    buffer = [];
  };
  for (const line of lines) {
    const heading = line.match(/^#{1,4}\s+(.+)$/) ?? line.match(/^(?:工作表|Sheet)\s*[:：]\s*(.+)$/i);
    if (heading) {
      flush();
      title = heading[1].trim() || `第 ${sections.length + 1} 节`;
    }
    buffer.push(line);
  }
  flush();
  return sections.length ? sections : [{ id: 'parsed-section-0', title: '全文', content }];
}

function ParsedContentViewer({ content, onLink }: { content: string; onLink: (href: string) => void }) {
  const [query, setQuery] = useState('');
  const sections = useMemo(() => parsedSections(content), [content]);
  const large = content.length > 120_000;
  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return needle
      ? sections.filter((section) => `${section.title}\n${section.content}`.toLocaleLowerCase().includes(needle))
      : sections;
  }, [query, sections]);
  const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  return (
    <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', gap: 8, padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, background: '#fff' }}>
        <Input allowClear prefix={<SearchOutlined />} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索解析内容" />
        <Select
          style={{ width: 210 }}
          placeholder="跳转到章节或工作表"
          options={sections.map((section) => ({ value: section.id, label: section.title }))}
          onChange={jump}
        />
      </div>
      <div className="wb-md" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: '16px 24px' }}>
        <Typography.Text type="secondary" style={{ display: 'block', marginBottom: 12, fontSize: 12 }}>
          这是提供给 AI 检索和分析的结构化文本，不代表原文件排版。{large ? ' 大文件已按章节延迟渲染，可逐节展开。' : ''}
        </Typography.Text>
        {!visible.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="没有找到匹配内容" />}
        {visible.map((section, index) => (
          <details
            id={section.id}
            key={section.id}
            open={!large || !!query || index === 0}
            style={{ contentVisibility: 'auto', containIntrinsicSize: '160px', marginBottom: 10, borderBottom: `1px solid ${WB.border}` }}
          >
            <summary style={{ position: 'sticky', top: 0, padding: '8px 0', background: '#fff', color: '#374151', fontWeight: 600, cursor: 'pointer', zIndex: 1 }}>
              {section.title}
            </summary>
            <MdNav content={section.content} onLink={onLink} />
          </details>
        ))}
      </div>
    </div>
  );
}

// ── 浏览器抽屉 ────────────────────────────────────────────────────────────
export interface BrowserDrawerProps {
  open: boolean;
  /** 每次打开时传入的初始 href（变化即触发新一轮导航，重置历史栈）。 */
  initialHref?: string | null;
  /** 稳定文件 ID 是跨工作空间打开的首选入口；href 仅用于网页和旧路径链接。 */
  initialFileId?: string | null;
  initialVersionId?: string | null;
  onClose: () => void;
  /** 把任意 href（http URL 或工作空间路径）解析为可渲染的 Source。 */
  resolveHref: (href: string) => Promise<Source>;
  loadFileById?: (fileId: string) => Promise<WorkspaceFile>;
  loadFileVersionById?: (fileId: string, versionId: string) => Promise<WorkspaceFile>;
  fallbackCapabilities?: WorkspaceFileCapabilities;
  fallbackWorkspaceName?: string;
  saveTextFile?: (fileId: string, data: {
    path: string; content: string; metadata?: Record<string, unknown>;
    base_version_id?: string | null; idempotency_key: string;
  }) => Promise<WorkspaceFile>;
  onReparse?: (fileId: string) => Promise<void>;
  /** 鉴权获取未经转换的原始文件，由浏览器按实际格式选择查看器。 */
  loadOriginalPreview?: (fileId: string, versionId?: string) => Promise<Blob>;
  /** 获取短时直连对象存储的预览源；历史文件会返回 blob 回退模式。 */
  loadOriginalPreviewSource?: (fileId: string, versionId?: string) => Promise<WorkspaceOriginalPreviewSource>;
  /** 获取 PDF 原页信息与逐页图像，避免大文件完整下载后才开始预览。 */
  loadPdfPreviewInfo?: (fileId: string, versionId?: string) => Promise<WorkspacePdfPreviewInfo>;
  loadPdfPreviewPage?: (fileId: string, pageNumber: number, versionId?: string) => Promise<Blob>;
  /** 鉴权下载未经转换的原始文件。 */
  loadOriginalFile?: (fileId: string, versionId?: string) => Promise<Blob>;
  /** 获取短时 OSS 直下载地址；下载字节不再经过 SaaS 后端。 */
  loadDownloadTicket?: (fileId: string, versionId?: string) => Promise<WorkspaceDownloadTicket>;
  loadPreviewSession?: (fileId: string, clientOpenId: string, preferredMode?: WorkspacePreviewPreferredMode, versionId?: string) => Promise<WorkspacePreviewSession>;
  refreshPreviewSession?: (fileId: string, accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  startFallbackPreview?: (fileId: string, versionId?: string) => Promise<WorkspaceFallbackPreview>;
  getFallbackPreview?: (fileId: string, versionId?: string) => Promise<WorkspaceFallbackPreview>;
  startSpreadsheetPreview?: (fileId: string, versionId?: string) => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheetPreview?: (fileId: string, versionId?: string) => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheetPage?: (fileId: string, sheet: string, page: number, versionId?: string) => Promise<WorkspaceSpreadsheetPage>;
  createEditSession?: (fileId: string, clientOpenId: string) => Promise<WorkspacePreviewSession>;
  refreshEditSession?: (fileId: string, roomId: string, accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  closeEditSession?: (fileId: string, clientOpenId: string) => Promise<WorkspaceOfficeEditStatus>;
  getEditSessionStatus?: (fileId: string, roomId: string) => Promise<WorkspaceOfficeEditStatus>;
  listFileVersions?: (fileId: string) => Promise<WorkspaceFileVersion[]>;
  restoreFileVersion?: (fileId: string, versionId: string, options: {
    base_version_id: string; idempotency_key: string;
  }) => Promise<WorkspaceFile>;
  onFileChanged?: (file: WorkspaceFile) => void;
  /** 其他用户或 Agent 写入后的服务端事件；当前预览会按稳定 file ID 原位刷新。 */
  externalVersionEvent?: WorkspaceFileEvent | null;
}

export default function BrowserDrawer({
  open, initialHref, initialFileId, initialVersionId, onClose, resolveHref, loadFileById, loadFileVersionById, fallbackCapabilities, fallbackWorkspaceName, saveTextFile, onReparse, loadOriginalPreview,
  loadOriginalPreviewSource, loadPdfPreviewInfo, loadPdfPreviewPage, loadOriginalFile, loadDownloadTicket,
  loadPreviewSession, refreshPreviewSession, startFallbackPreview, getFallbackPreview,
  startSpreadsheetPreview, getSpreadsheetPreview, getSpreadsheetPage,
  createEditSession, refreshEditSession, closeEditSession, getEditSessionStatus, listFileVersions, restoreFileVersion, onFileChanged, externalVersionEvent,
}: BrowserDrawerProps) {
  const [history, setHistory] = useState<Source[]>([]);
  const [index, setIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [editingText, setEditingText] = useState(false);
  const [textDraft, setTextDraft] = useState('');
  const [originalText, setOriginalText] = useState('');
  const [savingText, setSavingText] = useState(false);
  const [editingOffice, setEditingOffice] = useState(false);
  const [officeSaveState, setOfficeSaveState] = useState<{
    kind: 'editing' | 'reconciling' | 'saved' | 'unchanged' | 'failed';
    label: string;
  } | null>(null);
  const [csvMode, setCsvMode] = useState<'table' | 'text'>('table');
  const [csvDocument, setCsvDocument] = useState<CsvDocument | null>(null);
  const [csvSelection, setCsvSelection] = useState<{ anchor: [number, number]; focus: [number, number] } | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<WorkspaceFileVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [binaryView, setBinaryView] = useState<'original' | 'ai'>('original');
  const [originalPreviewBlob, setOriginalPreviewBlob] = useState<Blob | null>(null);
  const [originalPreviewUrl, setOriginalPreviewUrl] = useState<string | null>(null);
  const [originalPreviewHeaders, setOriginalPreviewHeaders] = useState<Record<string, string>>({});
  const [originalPreviewMime, setOriginalPreviewMime] = useState<string | null>(null);
  const [originalPreviewError, setOriginalPreviewError] = useState<string | null>(null);
  const [originalPreviewLoading, setOriginalPreviewLoading] = useState(false);
  // 标记某次 resolve 是否由"刷新"触发——刷新失败时回退展示旧内容，避免清屏。
  const refreshTickRef = useRef(0);
  const navigationSeqRef = useRef(0);
  const saveAttemptRef = useRef<{ fingerprint: string; key: string } | null>(null);
  const restoreAttemptRef = useRef<{ fingerprint: string; key: string } | null>(null);
  // index 的 ref 镜像：异步 navigate/refresh 完成后读取最新游标，避免闭包 stale 值。
  const indexRef = useRef(-1);
  useEffect(() => { indexRef.current = index; }, [index]);

  // 每次关闭预览后恢复为侧边抽屉，并真正卸载编辑会话。
  useEffect(() => {
    if (!open) {
      setIsFullscreen(false);
      setEditingText(false);
      setEditingOffice(false);
      setOfficeSaveState(null);
    }
  }, [open]);

  // 二进制 .docx → HTML 的客户端转换结果。current 切换或刷新时重算。
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [docxError, setDocxError] = useState<string | null>(null);

  const current = index >= 0 ? history[index] : null;
  const canBack = index > 0;
  const canForward = index >= 0 && index < history.length - 1;
  const currentFileId = current && 'fileId' in current ? current.fileId : null;
  const currentPath = current && 'path' in current ? current.path : null;
  const underlyingCapabilities = current?.file?.capabilities
    ?? current?.file?.effective_capabilities
    ?? fallbackCapabilities;
  const currentCapabilities = current?.versionId
    ? { ...underlyingCapabilities, update: false }
    : underlyingCapabilities;
  const canRestoreCurrent = underlyingCapabilities?.read === true && underlyingCapabilities.update === true;
  const canUpdateCurrent = !!currentFileId && currentCapabilities?.read === true && currentCapabilities.update === true;
  const currentExtension = currentPath ? extOf(currentPath) : '';
  const canEditText = canUpdateCurrent && !!saveTextFile
    && ['txt', 'md', 'markdown', 'json', 'csv'].includes(currentExtension);
  const canEditOffice = canUpdateCurrent && current?.file?.office_edit_enabled === true
    && !!createEditSession && !!refreshEditSession
    && OFFICE_EDIT_EXTS.has(currentExtension)
    && (current?.file?.size ?? Number.POSITIVE_INFINITY) <= OFFICE_EDIT_MAX_BYTES;

  useEffect(() => {
    setEditingText(false);
    setEditingOffice(false);
    setTextDraft('');
    setOriginalText('');
    setCsvDocument(null);
    setCsvSelection(null);
    setOfficeSaveState(null);
    saveAttemptRef.current = null;
    restoreAttemptRef.current = null;
  }, [currentFileId]);

  // 同一稳定 fileId 的当前版本可能被其他成员更新；空闲预览时轻量轮询并原位刷新。
  useEffect(() => {
    if (!open || !currentFileId || current?.versionId || editingText || editingOffice || !loadFileById || !current?.file) return;
    const displayedVersionId = current.file?.current_version_id;
    const displayedUpdatedAt = current.file?.updated_at;
    let disposed = false;
    let busy = false;
    const check = async () => {
      if (busy) return;
      busy = true;
      try {
        const file = await loadFileById(currentFileId);
        if (!disposed && (file.current_version_id !== displayedVersionId || file.updated_at !== displayedUpdatedAt)) {
          const next = classifyFile(file);
          const at = indexRef.current;
          setHistory((items) => { const copy = [...items]; copy[at] = next; return copy; });
          onFileChanged?.(file);
        }
      } catch { /* 权限撤回或临时网络错误由用户主动刷新时明确显示。 */ }
      finally { busy = false; }
    };
    const timer = window.setInterval(() => { void check(); }, 5000);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [current?.file?.current_version_id, current?.file?.updated_at, current?.versionId, currentFileId, editingOffice, editingText, loadFileById, onFileChanged, open]);

  useEffect(() => {
    setBinaryView('original');
    setOriginalPreviewError(null);
    setOriginalPreviewBlob(null);
    setOriginalPreviewUrl(null);
    setOriginalPreviewHeaders({});
    setOriginalPreviewMime(null);
    setOriginalPreviewLoading(false);
    if (!current || (current.kind !== 'parsed' && current.kind !== 'binary')
      || (!loadOriginalPreviewSource && !loadOriginalPreview)) return;
    if (loadPreviewSession) return;
    if (supportsPagedWorkspacePreview(displayNameFromPath(current.path))
      && loadPdfPreviewInfo && loadPdfPreviewPage) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setOriginalPreviewLoading(true);
    const load = async () => {
      if (loadOriginalPreviewSource) {
        const source = await loadOriginalPreviewSource(current.fileId, current.versionId);
        if (cancelled) return;
        setOriginalPreviewMime(source.mime_type);
        if (source.mode === 'url' && source.url) {
          const headers = { ...(source.headers || {}), Range: 'bytes=0-0' };
          let selectedUrl = source.url;
          try {
            const probe = await fetch(source.url, { headers });
            if (!probe.ok && source.fallback_url) selectedUrl = source.fallback_url;
          } catch {
            if (source.fallback_url) selectedUrl = source.fallback_url;
          }
          setOriginalPreviewHeaders(source.headers || {});
          setOriginalPreviewUrl(selectedUrl);
          return;
        }
      }
      if (!loadOriginalPreview) throw new Error('原文件预览回退不可用');
      const blob = await loadOriginalPreview(current.fileId, current.versionId);
      if (cancelled) return;
      objectUrl = URL.createObjectURL(blob);
      setOriginalPreviewBlob(blob);
      setOriginalPreviewUrl(objectUrl);
    };
    load()
      .catch((error) => {
        if (!cancelled) setOriginalPreviewError((error as Error)?.message || '原文件预览加载失败');
      })
      .finally(() => { if (!cancelled) setOriginalPreviewLoading(false); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [current, loadOriginalPreview, loadOriginalPreviewSource, loadPdfPreviewInfo, loadPdfPreviewPage, loadPreviewSession]);

  useEffect(() => {
    if (current?.kind !== 'docx-bin') { setDocxHtml(null); setDocxError(null); return; }
    let cancelled = false;
    setLoading(true);
    setDocxError(null);
    (async () => {
      try {
        const bytes = b64ToUint8(current.content);
        const mammoth = (await import('mammoth/mammoth.browser')).default;
        const res = await mammoth.convertToHtml({ arrayBuffer: bytes.buffer });
        if (cancelled) return;
        setDocxHtml(wrapDocxHtml(res.value || '<p style="color:#9ca3af">（文档内容为空）</p>'));
      } catch (e) {
        if (cancelled) return;
        setDocxError((e as Error)?.message || '无法解析该 .docx 文件');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current, refreshKey]);

  const pushSource = useCallback((src: Source) => {
    const at = indexRef.current;
    setHistory((h) => [...h.slice(0, at + 1), src]);
    setIndex(at + 1);
    setRefreshKey((k) => k + 1);
  }, []);

  const resolveFileId = useCallback(async (fileId: string, versionId?: string | null): Promise<Source> => {
    if (versionId && !loadFileVersionById) {
      return { kind: 'unsupported', href: `/f/${fileId}?version=${encodeURIComponent(versionId)}`, versionId, note: '该历史版本暂不支持在线读取；未回退到当前版本' };
    }
    if (!loadFileById) return { kind: 'unsupported', href: `/f/${fileId}`, note: '当前入口不支持按文件 ID 打开' };
    try {
      const source = classifyFile(versionId
        ? await loadFileVersionById!(fileId, versionId)
        : await loadFileById(fileId));
      source.versionId = versionId || undefined;
      return source;
    } catch (error) {
      const status = (error as { status?: number })?.status;
      return {
        kind: 'unsupported', href: `/f/${fileId}`,
        note: status === 403 ? '你没有权限查看该文件' : status === 404 ? '文件不存在或已删除' : '文件详情读取失败',
      };
    }
  }, [loadFileById, loadFileVersionById]);

  // 解析并压入历史栈（清掉前进部分），用于初始打开与点击内部链接。
  const navigate = useCallback(async (href: string) => {
    const navigationSeq = ++navigationSeqRef.current;
    setLoading(true);
    let src: Source;
    try {
      const internalRef = parseWorkspaceInternalUrl(href);
      src = internalRef ? await resolveFileId(internalRef.fileId, internalRef.versionId) : await resolveHref(href);
    } catch {
      src = { kind: 'unsupported', href, note: '无法加载该资源' };
    }
    if (navigationSeq !== navigationSeqRef.current) return;
    setLoading(false);
    pushSource(src);
  }, [pushSource, resolveFileId, resolveHref]);

  // initialHref 变化且抽屉打开 → 重置历史并导航到新源
  useEffect(() => {
    let cancelled = false;
    if (open && (initialFileId || initialHref)) {
      setEditingText(false);
      setEditingOffice(false);
      setTextDraft('');
      setOriginalText('');
      setHistory([]);
      setIndex(-1);
      indexRef.current = -1;
      if (initialFileId) {
        const navigationSeq = ++navigationSeqRef.current;
        setLoading(true);
        void resolveFileId(initialFileId, initialVersionId).then((source) => {
          if (cancelled || navigationSeq !== navigationSeqRef.current) return;
          setLoading(false);
          pushSource(source);
        });
      } else if (initialHref) {
        void navigate(initialHref);
      }
    }
    return () => {
      cancelled = true;
      navigationSeqRef.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialFileId, initialVersionId, initialHref, open]);

  const moveHistory = (offset: -1 | 1) => {
    const move = () => {
      setEditingText(false);
      setEditingOffice(false);
      setIndex((value) => value + offset);
      setRefreshKey((value) => value + 1);
    };
    if (!(editingText && textDraft !== originalText)) { move(); return; }
    Modal.confirm({
      title: '放弃未保存的修改？',
      content: '切换文件会丢弃当前草稿。',
      okText: '放弃并切换', cancelText: '继续编辑', okButtonProps: { danger: true },
      onOk: move,
    });
  };
  const goBack = () => { if (canBack) moveHistory(-1); };
  const goForward = () => { if (canForward) moveHistory(1); };

  // 刷新：URL 类直接重载 iframe；文件类重新解析当前 href
  const refresh = async () => {
    if (!current) return;
    if (current.kind === 'web' || current.kind === 'pdf' || current.kind === 'docx') {
      setRefreshKey((k) => k + 1);
      return;
    }
    // 文件优先按稳定 ID 刷新，避免跨工作空间同名路径误开。
    refreshTickRef.current += 1;
    const tick = refreshTickRef.current;
    setLoading(true);
    let src: Source;
    try { src = currentFileId ? await resolveFileId(currentFileId, current.versionId) : await resolveHref(current.href); }
    catch { src = { kind: 'unsupported', href: current.href, note: '无法加载该资源' }; }
    if (tick !== refreshTickRef.current) return; // 已被更新的刷新覆盖
    setLoading(false);
    const at = indexRef.current;
    setHistory((h) => { const n = [...h]; n[at] = src; return n; });
    if (src.file) onFileChanged?.(src.file);
    setRefreshKey((k) => k + 1);
  };

  const handledExternalEventRef = useRef(0);
  useEffect(() => {
    if (!externalVersionEvent || externalVersionEvent.id <= handledExternalEventRef.current) return;
    if (!open || externalVersionEvent.file_id !== currentFileId || current?.versionId) return;
    handledExternalEventRef.current = externalVersionEvent.id;
    // 本地文本草稿靠 base_version_id 在保存时提示冲突；Office 编辑会话由保存对账流程接管。
    if (editingText || editingOffice) return;
    // 即使 version_id 未变也要刷新：重命名、移动、删除和权限变化都可能保留同一版本号。
    void refresh();
    // refresh 读取当前稳定 file ID；事件只作为失效信号，不携带文件正文。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalVersionEvent?.id]);

  const startTextEdit = async () => {
    if (!current || !canEditText || !currentFileId || !currentPath) return;
    try {
      let content = 'content' in current ? current.content : '';
      if (currentExtension === 'csv' && current.file?.metadata?.binary && loadOriginalFile) {
        content = await (await loadOriginalFile(currentFileId)).text();
      }
      setTextDraft(content);
      setOriginalText(content);
      if (currentExtension === 'csv') {
        setCsvDocument(parseCsvDocument(content));
        setCsvMode('table');
      }
      setEditingText(true);
    } catch (error) {
      message.error((error as Error)?.message || '编辑内容加载失败');
    }
  };

  const updateCsvCell = (rowIndex: number, columnIndex: number, value: string) => {
    setCsvDocument((currentDocument) => {
      if (!currentDocument) return currentDocument;
      const rows = currentDocument.rows.map((row) => [...row]);
      while (rows[rowIndex].length <= columnIndex) rows[rowIndex].push('');
      rows[rowIndex][columnIndex] = value;
      const next = { ...currentDocument, rows };
      setTextDraft(serializeCsvDocument(next));
      return next;
    });
  };
  const csvColumnCount = useMemo(
    () => Math.max(1, ...(csvDocument?.rows.slice(0, 500).map((item) => item.length) ?? [1])),
    [csvDocument],
  );
  const csvSelectionBounds = csvSelection ? {
    top: Math.min(csvSelection.anchor[0], csvSelection.focus[0]),
    bottom: Math.max(csvSelection.anchor[0], csvSelection.focus[0]),
    left: Math.min(csvSelection.anchor[1], csvSelection.focus[1]),
    right: Math.max(csvSelection.anchor[1], csvSelection.focus[1]),
  } : null;
  const copyCsvSelection = (event: ReactClipboardEvent<HTMLDivElement>) => {
    if (!csvDocument || !csvSelectionBounds) return;
    const value = csvDocument.rows
      .slice(csvSelectionBounds.top, csvSelectionBounds.bottom + 1)
      .map((row) => Array.from(
        { length: csvSelectionBounds.right - csvSelectionBounds.left + 1 },
        (_, offset) => row[csvSelectionBounds.left + offset] ?? '',
      ).join('\t'))
      .join('\n');
    event.preventDefault();
    event.clipboardData.setData('text/plain', value);
  };

  const saveText = async () => {
    if (!current || !currentFileId || !currentPath || !saveTextFile) return;
    if (currentExtension === 'json') {
      try { JSON.parse(textDraft); }
      catch { message.error('JSON 格式无效，请修正后再保存'); return; }
    }
    setSavingText(true);
    try {
      const fingerprint = `${currentFileId}\u0000${current.file?.current_version_id || ''}\u0000${textDraft}`;
      if (saveAttemptRef.current?.fingerprint !== fingerprint) {
        saveAttemptRef.current = { fingerprint, key: crypto.randomUUID() };
      }
      const nextFile = await saveTextFile(currentFileId, {
        path: currentPath,
        content: textDraft,
        metadata: current.file?.metadata,
        base_version_id: current.file?.current_version_id ?? null,
        idempotency_key: saveAttemptRef.current.key,
      });
      const next = classifyFile(nextFile);
      const at = indexRef.current;
      setHistory((items) => { const copy = [...items]; copy[at] = next; return copy; });
      setEditingText(false);
      setOriginalText(textDraft);
      saveAttemptRef.current = null;
      onFileChanged?.(nextFile);
      message.success('已保存为新版本');
    } catch (error) {
      const status = (error as { status?: number })?.status;
      message.error(status === 409 ? '文件已有更新，请刷新后再保存，未覆盖他人的版本' : ((error as Error)?.message || '保存失败'));
    } finally {
      setSavingText(false);
    }
  };

  const textDirty = editingText && textDraft !== originalText;
  useEffect(() => {
    if (!textDirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', guard);
    return () => window.removeEventListener('beforeunload', guard);
  }, [textDirty]);

  const cancelTextEdit = () => {
    if (!textDirty) { setEditingText(false); return; }
    Modal.confirm({
      title: '放弃未保存的修改？',
      content: '草稿只保存在当前浏览器中，放弃后无法恢复。',
      okText: '放弃修改', cancelText: '继续编辑', okButtonProps: { danger: true },
      onOk: () => setEditingText(false),
    });
  };
  const discardAndClose = () => {
    setEditingText(false);
    setEditingOffice(false);
    setTextDraft('');
    setOriginalText('');
    onClose();
  };
  const closeDrawer = () => {
    if (!textDirty) { discardAndClose(); return; }
    Modal.confirm({
      title: '关闭并放弃未保存的修改？',
      content: '草稿只保存在当前浏览器中，关闭后无法恢复。',
      okText: '关闭', cancelText: '继续编辑', okButtonProps: { danger: true },
      onOk: discardAndClose,
    });
  };

  const copyInternalAddress = async () => {
    if (!currentFileId) return;
    const url = workspaceInternalUrl(current?.file ?? { id: currentFileId, workspace_id: '', path: currentPath || '' }, window.location.origin, current?.versionId);
    try {
      await navigator.clipboard.writeText(url);
      message.success('文件地址已复制；有权限的成员可打开');
    } catch {
      Modal.info({
        title: '复制文件地址',
        content: <Input readOnly value={url} onFocus={(event) => event.currentTarget.select()} />,
        okText: '关闭',
      });
    }
  };

  const openVersionHistory = async () => {
    if (!currentFileId || !listFileVersions) return;
    setVersionsOpen(true);
    setVersionsLoading(true);
    try { setVersions(await listFileVersions(currentFileId)); }
    catch (error) { message.error((error as Error)?.message || '版本历史加载失败'); }
    finally { setVersionsLoading(false); }
  };

  const copyVersionAddress = async (versionId: string) => {
    if (!currentFileId) return;
    const url = workspaceInternalUrl(current?.file ?? { id: currentFileId, workspace_id: '', path: currentPath || '' }, window.location.origin, versionId);
    try {
      await navigator.clipboard.writeText(url);
      message.success('历史版本地址已复制');
    } catch {
      Modal.info({ title: '复制历史版本地址', content: <Input readOnly value={url} onFocus={(event) => event.currentTarget.select()} />, okText: '关闭' });
    }
  };

  const restoreVersion = (version: WorkspaceFileVersion) => {
    if (!currentFileId || !restoreFileVersion || !canRestoreCurrent) return;
    const baseVersionId = current?.file?.current_version_id;
    if (!baseVersionId) {
      message.error('当前文件版本信息不可用，请刷新后重试');
      return;
    }
    Modal.confirm({
      title: `恢复版本 ${version.version_no}？`,
      content: '恢复不会覆盖历史记录，而是基于该版本创建一个新的当前版本。',
      okText: '恢复为新版本', cancelText: '取消',
      onOk: async () => {
        try {
          const fingerprint = `${currentFileId}\u0000${baseVersionId}\u0000${version.id}`;
          if (restoreAttemptRef.current?.fingerprint !== fingerprint) {
            restoreAttemptRef.current = { fingerprint, key: crypto.randomUUID() };
          }
          const nextFile = await restoreFileVersion(currentFileId, version.id, {
            base_version_id: baseVersionId,
            idempotency_key: restoreAttemptRef.current.key,
          });
          const next = classifyFile(nextFile);
          const at = indexRef.current;
          setHistory((items) => { const copy = [...items]; copy[at] = next; return copy; });
          onFileChanged?.(nextFile);
          setVersions(await listFileVersions!(currentFileId));
          restoreAttemptRef.current = null;
          message.success('已恢复为新的当前版本');
        } catch (error) {
          const status = (error as { status?: number })?.status;
          message.error(status === 409 ? '当前文件已被更新，请刷新版本列表后重试' : ((error as Error)?.message || '版本恢复失败'));
          throw error;
        }
      },
    });
  };

  const finishOfficeEdit = async (result?: { roomId: string; status: WorkspaceOfficeEditStatus | null }) => {
    setEditingOffice(false);
    if (!currentFileId || !loadFileById) return;
    const fileId = currentFileId;
    const historyIndex = indexRef.current;
    if (!result?.roomId || !getEditSessionStatus) {
      setOfficeSaveState(result?.roomId ? { kind: 'reconciling', label: '保存对账中' } : null);
      message.info('编辑已结束；平台仍在后台保存对账，请稍后刷新或查看版本历史');
      return;
    }
    setOfficeSaveState({ kind: 'reconciling', label: '保存对账中' });
    const hide = message.loading('编辑已结束，正在等待平台保存对账…', 0);
    try {
      let status = result.status;
      for (let attempt = 0; attempt < 30; attempt += 1) {
        if (!status || attempt > 0) status = await getEditSessionStatus(fileId, result.roomId);
        const outcome = workspaceOfficeEditOutcome(status);
        if (outcome.kind === 'saved') {
          const file = await loadFileById(fileId);
          const next = classifyFile(file);
          setHistory((items) => {
            const displayed = items[historyIndex];
            if (!displayed || !('fileId' in displayed) || displayed.fileId !== fileId) return items;
            const copy = [...items];
            copy[historyIndex] = next;
            return copy;
          });
          onFileChanged?.(file);
          setOfficeSaveState({ kind: 'saved', label: `已保存 · ${outcome.finalFileVersionId.slice(0, 8)}` });
          message.success(`本次编辑已保存为新版本（${outcome.finalFileVersionId.slice(0, 8)}）`);
          return;
        }
        if (outcome.kind === 'unchanged') {
          setOfficeSaveState({ kind: 'unchanged', label: '已结束 · 无新版本' });
          message.info('编辑已结束，本次没有产生新的文件版本');
          return;
        }
        if (outcome.kind === 'failed') {
          setOfficeSaveState({ kind: 'failed', label: '保存失败' });
          message.error(`本次编辑保存失败：${outcome.error}`);
          return;
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2000));
      }
      setOfficeSaveState({ kind: 'reconciling', label: '保存对账中' });
      message.info('本次编辑仍在保存对账，可稍后刷新或查看版本历史');
    } catch (error) {
      setOfficeSaveState({ kind: 'failed', label: '状态查询失败' });
      message.error((error as Error)?.message || '本次编辑保存状态查询失败，请稍后查看版本历史');
    } finally {
      hide();
    }
  };

  const reparse = async () => {
    if (!current || (current.kind !== 'binary' && current.kind !== 'parsed') || !onReparse) return;
    setLoading(true);
    try {
      await onReparse(current.fileId);
      const src = await resolveHref(current.href);
      const at = indexRef.current;
      setHistory((h) => { const n = [...h]; n[at] = src; return n; });
      setRefreshKey((k) => k + 1);
    } catch (e) {
      message.error((e as Error)?.message || '重新解析失败');
    } finally {
      setLoading(false);
    }
  };

  // 在新标签页打开：URL 直接打开；文件类生成 blob 预览
  const openInNewTab = () => {
    if (!current) return;
    // 即使使用 noopener，同源 text/html Blob 仍可以读取平台存储和调用 API。
    // 不可信工作空间 HTML 只允许在抽屉中以纯文本查看或下载。
    if (current.kind === 'html-text') return;
    if ((current.kind === 'parsed' || current.kind === 'binary') && binaryView === 'original' && originalPreviewUrl) {
      window.open(originalPreviewUrl, '_blank', 'noopener');
      return;
    }
    if (current.kind === 'web' || current.kind === 'pdf' || current.kind === 'docx') {
      window.open(current.url, '_blank', 'noopener');
      return;
    }
    if (current.kind === 'docx-bin') {
      const blob = new Blob([b64ToUint8(current.content)], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      return;
    }
    if (current.kind === 'parsed') {
      const blob = new Blob([current.content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      return;
    }
    if (current.kind === 'image') {
      window.open(current.src, '_blank', 'noopener');
      return;
    }
    if (current.kind === 'md' || current.kind === 'text') {
      const mime = current.kind === 'md' ? 'text/markdown' : 'text/plain';
      const blob = new Blob([current.content], { type: `${mime};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      return;
    }
    if (current.kind === 'unsupported' && current.url) window.open(current.url, '_blank', 'noopener');
  };

  // 下载当前预览内容：工作空间文件→内容 blob 下载；外部 URL→新标签打开由浏览器处理
  const saveBlob = (blob: Blob, filename: string) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  };

  const download = async () => {
    if (!current) return;
    if (current.kind === 'image') {
      // data: URL 直接作为下载锚点；http URL 退化为新标签打开（跨域限制）
      const a = document.createElement('a');
      a.href = current.src;
      a.download = current.path ? displayNameFromPath(current.path) : 'image';
      document.body.appendChild(a);
      a.click();
      a.remove();
      return;
    }
    if (current.kind === 'md' || current.kind === 'text' || current.kind === 'html-text') {
      // HTML 下载使用二进制响应，避免浏览器在 download 属性失效时将其当作
      // 同源可执行文档导航；字节内容和原始文件名保持不变。
      const mime = current.kind === 'html-text' ? 'application/octet-stream'
        : current.kind === 'md' ? 'text/markdown' : 'text/plain';
      const blob = new Blob([current.content], { type: `${mime};charset=utf-8` });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = displayNameFromPath(current.path);
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      return;
    }
    if (current.kind === 'web' || current.kind === 'pdf' || current.kind === 'docx') {
      window.open(current.url, '_blank', 'noopener');
      return;
    }
    if (current.kind === 'docx-bin') {
      const blob = new Blob([b64ToUint8(current.content)], { type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = displayNameFromPath(current.path);
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      return;
    }
    if (current.kind === 'parsed' || current.kind === 'binary') {
      try {
        if (loadDownloadTicket) {
          const ticket = await loadDownloadTicket(current.fileId, current.versionId);
          let target = ticket.url;
          try {
            const probe = await fetch(ticket.url, {
              headers: { ...ticket.headers, Range: 'bytes=0-0' },
            });
            if (!probe.ok && ticket.fallback_url) target = ticket.fallback_url;
          } catch {
            if (ticket.fallback_url) target = ticket.fallback_url;
          }
          const anchor = document.createElement('a');
          anchor.href = target;
          anchor.download = ticket.filename || displayNameFromPath(current.path);
          anchor.target = '_blank';
          anchor.rel = 'noopener';
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
          return;
        }
        const blob = loadOriginalFile
          ? await loadOriginalFile(current.fileId, current.versionId)
          : new Blob([b64ToUint8(current.kind === 'parsed' ? current.originalContent : current.content)], { type: current.mime });
        saveBlob(blob, displayNameFromPath(current.path));
      } catch (error) {
        if (error && (error as { status?: number }).status === 409 && loadOriginalFile) {
          try {
            const blob = await loadOriginalFile(current.fileId, current.versionId);
            saveBlob(blob, displayNameFromPath(current.path));
            return;
          } catch (fallbackError) {
            message.error((fallbackError as Error)?.message || '原文件下载失败');
            return;
          }
        }
        message.error((error as Error)?.message || '原文件下载失败');
      }
    }
  };

  const navBtn = (onClick: () => void, disabled: boolean, icon: ReactNode, title: string) => (
    <Tooltip title={title}>
      <button
        type="button"
        aria-label={title}
        onClick={onClick} disabled={disabled}
        style={navBtnStyle(disabled)}
      >{icon}</button>
    </Tooltip>
  );

  const rawAddr = current?.href ?? '';
  const addr = current?.file
    ? workspaceFileLabel({ ...current.file, workspace_name: current.file.workspace_name || fallbackWorkspaceName })
    : current?.kind === 'web' || current?.kind === 'pdf' || current?.kind === 'docx'
    ? rawAddr
    : rawAddr;
  const addrIcon =
    current?.kind === 'web' ? <GlobalOutlined /> :
    current?.kind === 'pdf' ? <FilePdfOutlined /> :
    current?.kind === 'docx' || current?.kind === 'docx-bin' ? <FileWordOutlined /> :
    current?.kind === 'image' ? <FileImageOutlined /> :
    current?.kind === 'md' || current?.kind === 'text' || current?.kind === 'html-text' || current?.kind === 'parsed' || current?.kind === 'binary' ? <FileTextOutlined /> :
    <SelectOutlined />;

  return (
    <Drawer
      placement="right"
      open={open}
      width={isFullscreen ? '100vw' : 'min(760px, 100vw)'}
      onClose={closeDrawer}
      rootClassName="wb-browser-drawer"
      styles={{
        header: { display: 'none' },
        body: { padding: 0, background: '#fff', display: 'flex', flexDirection: 'column' },
      }}
      rootStyle={{ fontFamily: WB_FONT }}
    >
      {/* 浏览器工具栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto' }}>
        {navBtn(goBack, !canBack, <ArrowLeftOutlined />, '后退')}
        {navBtn(goForward, !canForward, <ArrowRightOutlined />, '前进')}
        {navBtn(refresh, false, <ReloadOutlined />, '刷新')}
        {/* 地址栏 */}
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', gap: 6,
          height: 30, padding: '0 10px', borderRadius: 15,
          background: '#F3F4F6', color: '#4b5563', fontSize: 12,
          overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis',
        }}>
          <span style={{ color: '#9ca3af', flex: '0 0 auto' }}>{addrIcon}</span>
          <Tooltip title={addr || undefined} mouseEnterDelay={0.5}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{addr || 'about:blank'}</span>
          </Tooltip>
        </div>
        {canEditText && !editingText && navBtn(() => { void startTextEdit(); }, false, <EditOutlined />, currentExtension === 'csv' ? '以安全文本模式编辑 CSV' : '编辑文件')}
        {canEditOffice && !editingOffice && navBtn(() => {
          setOfficeSaveState({ kind: 'editing', label: '编辑中 · 自动保存' });
          setEditingOffice(true);
        }, false, <EditOutlined />, '协同编辑')}
        {editingText && navBtn(() => { void saveText(); }, savingText, <SaveOutlined />, '保存为新版本')}
        {!!currentFileId && !!listFileVersions && navBtn(() => { void openVersionHistory(); }, false, <HistoryOutlined />, '版本历史')}
        {navBtn(download, false, <DownloadOutlined />, '下载')}
        {!!currentFileId && navBtn(() => { void copyInternalAddress(); }, false, <LinkOutlined />, '复制文件地址')}
        {navBtn(
          () => setIsFullscreen((value) => !value),
          false,
          isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />,
          isFullscreen ? '退出全屏预览' : '全屏预览',
        )}
        {current?.kind !== 'html-text' && navBtn(openInNewTab, false, <ExportOutlined />, '在新标签页中打开')}
        <Button size="small" type="text" onClick={closeDrawer} style={{ color: '#6b7280' }}>关闭</Button>
      </div>

      {!!currentFileId && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', borderBottom: `1px solid ${WB.border}`, background: '#fafafa', flex: '0 0 auto', fontSize: 12 }}>
          <Typography.Text ellipsis={{ tooltip: addr }} style={{ flex: 1, minWidth: 0 }}>{addr}</Typography.Text>
          {(current?.versionId ? current.file?.resolved_version_no : current?.file?.current_version_no) != null && (
            <Tag style={{ margin: 0 }}>版本 {current?.versionId ? current.file?.resolved_version_no : current?.file?.current_version_no}</Tag>
          )}
          {officeSaveState && (
            <Tag
              color={officeSaveState.kind === 'saved' ? 'green'
                : officeSaveState.kind === 'failed' ? 'red'
                  : officeSaveState.kind === 'unchanged' ? 'default' : 'gold'}
              style={{ margin: 0 }}
            >
              {officeSaveState.label}
            </Tag>
          )}
          <Tag color={currentCapabilities?.read ? 'green' : 'default'} style={{ margin: 0 }}>{currentCapabilities?.read ? '可查看' : '只读状态未知'}</Tag>
          {currentCapabilities?.update && <Tag color="blue" style={{ margin: 0 }}>可编辑</Tag>}
        </div>
      )}

      {/* 内容区 */}
      <div style={{ flex: 1, minHeight: 0, position: 'relative', background: '#fff' }}>
        {loading && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(255,255,255,0.7)', zIndex: 2 }}>
            <Spin />
          </div>
        )}
        {!current && !loading && (
          <div style={{ padding: 40 }}><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未指定地址" /></div>
        )}
        {!editingText && !editingOffice && current?.kind === 'web' && (
          <iframe key={refreshKey} src={current.url} title="web"
            style={{ width: '100%', height: '100%', border: 'none' }}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox" />
        )}
        {!editingText && !editingOffice && current?.kind === 'pdf' && (
          <iframe key={refreshKey} src={current.url} title="pdf"
            style={{ width: '100%', height: '100%', border: 'none' }} />
        )}
        {!editingText && !editingOffice && current?.kind === 'docx' && (
          <iframe key={refreshKey} src={gviewUrl(current.url)} title="docx"
            style={{ width: '100%', height: '100%', border: 'none' }} />
        )}
        {!editingText && !editingOffice && current?.kind === 'docx-bin' && (
          docxError ? (
            <div style={{ padding: 40, textAlign: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={<>
                  <div>{docxError}</div>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>{current.href}</Typography.Text>
                </>} />
              <Button type="link" icon={<DownloadOutlined />} onClick={download}>下载原文件</Button>
            </div>
          ) : docxHtml ? (
            <iframe key={refreshKey} srcDoc={docxHtml} title="docx"
              style={{ width: '100%', height: '100%', border: 'none' }}
              sandbox="allow-same-origin allow-popups" />
          ) : null
        )}
        {editingText && currentFileId && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 14, gap: 10, background: '#fafafa' }}>
            {currentExtension === 'csv' && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <Alert style={{ flex: 1 }} type="info" showIcon message="CSV 编辑保留 BOM、原换行风格和尾换行；数值不会自动转换。" />
                <Segmented
                  value={csvMode}
                  options={[{ label: '表格', value: 'table' }, { label: '安全文本', value: 'text' }]}
                  onChange={(value) => {
                    const nextMode = value as 'table' | 'text';
                    if (nextMode === 'table') setCsvDocument(parseCsvDocument(textDraft));
                    setCsvMode(nextMode);
                  }}
                />
              </div>
            )}
            {currentExtension === 'csv' && csvMode === 'table' && csvDocument ? (
              <div
                tabIndex={0}
                onCopy={copyCsvSelection}
                style={{ flex: 1, minHeight: 0, overflow: 'auto', border: `1px solid ${WB.border}`, background: '#fff', outline: 'none' }}
              >
                {csvDocument.rows.length > 500 && <Alert banner type="warning" message="表格模式仅显示前 500 行；切到安全文本模式可编辑全部内容。" />}
                <table style={{ borderCollapse: 'collapse', minWidth: '100%', tableLayout: 'fixed' }}>
                  <tbody>
                    {csvDocument.rows.slice(0, 500).map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        <th style={{ width: 48, minWidth: 48, padding: '4px 6px', border: `1px solid ${WB.border}`, background: '#f3f4f6', color: '#6b7280', fontWeight: 500 }}>{rowIndex + 1}</th>
                        {Array.from({ length: csvColumnCount }, (_, columnIndex) => {
                          const selected = !!csvSelectionBounds
                            && rowIndex >= csvSelectionBounds.top && rowIndex <= csvSelectionBounds.bottom
                            && columnIndex >= csvSelectionBounds.left && columnIndex <= csvSelectionBounds.right;
                          return (
                          <td
                            key={columnIndex}
                            onMouseDown={(event) => {
                              const cell: [number, number] = [rowIndex, columnIndex];
                              setCsvSelection((current) => event.shiftKey && current ? { ...current, focus: cell } : { anchor: cell, focus: cell });
                            }}
                            onMouseEnter={(event) => {
                              if (event.buttons === 1) setCsvSelection((current) => current ? { ...current, focus: [rowIndex, columnIndex] } : current);
                            }}
                            style={{ minWidth: 140, padding: 0, border: `1px solid ${selected ? WB.primary : WB.border}`, background: selected ? '#eef2ff' : '#fff' }}
                          >
                            <Input
                              bordered={false}
                              value={row[columnIndex] ?? ''}
                              onChange={(event) => updateCsvCell(rowIndex, columnIndex, event.target.value)}
                              style={{ minWidth: 140, borderRadius: 0, fontFamily: 'Consolas, "SFMono-Regular", monospace', background: 'transparent' }}
                            />
                          </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Input.TextArea
                autoFocus
                value={textDraft}
                onChange={(event) => setTextDraft(event.target.value)}
                spellCheck={false}
                style={{ flex: 1, resize: 'none', fontFamily: 'Consolas, "SFMono-Regular", monospace', fontSize: 13, lineHeight: 1.55 }}
              />
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
              <Button onClick={cancelTextEdit} disabled={savingText}>取消</Button>
              <Button type="primary" icon={<SaveOutlined />} loading={savingText} onClick={() => { void saveText(); }}>保存为新版本</Button>
            </div>
          </div>
        )}
        {editingOffice && currentFileId && createEditSession && refreshEditSession && (
          <WorkspaceEditSessionView
            key={`edit:${currentFileId}`}
            fileId={currentFileId}
            filename={currentPath || 'Office 文件'}
            loadSession={(clientOpenId) => createEditSession(currentFileId, clientOpenId)}
            refreshSession={(roomId, accessToken, refreshToken, refreshContext) => refreshEditSession(currentFileId, roomId, accessToken, refreshToken, refreshContext)}
            closeSession={closeEditSession ? (clientOpenId) => closeEditSession(currentFileId, clientOpenId) : undefined}
            onExit={(result) => { void finishOfficeEdit(result); }}
          />
        )}
        {!editingText && !editingOffice && current?.kind === 'md' && (
          <div className="wb-md" style={{ height: '100%', overflowY: 'auto', padding: '20px 24px' }}>
            <MdNav content={current.content} onLink={navigate} />
          </div>
        )}
        {!editingText && !editingOffice && (current?.kind === 'parsed' || current?.kind === 'binary') && (
          <div style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column' }}>
            <div style={{
              flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              gap: 12, padding: '8px 14px', borderBottom: `1px solid ${WB.border}`, background: '#FAFAFB',
            }}>
              <Segmented
                size="small"
                value={binaryView}
                onChange={(value) => setBinaryView(value as 'original' | 'ai')}
                options={[
                  { label: '原文件预览', value: 'original' },
                  { label: 'AI 解析内容', value: 'ai', disabled: current.kind !== 'parsed' },
                ]}
              />
              <div style={{ display: 'flex', gap: 6 }}>
                <Tag color="blue">原文件</Tag>
                {current.kind === 'parsed' && <Tag color="green">AI 已解析</Tag>}
              </div>
            </div>
            <div style={{ flex: 1, minHeight: 0, position: 'relative' }}>
              {binaryView === 'original' && (
                <OriginalFilePreview
                  key={current.fileId}
                  previewKey={current.fileId}
                  blob={originalPreviewBlob}
                  sourceUrl={originalPreviewUrl}
                  sourceHeaders={originalPreviewHeaders}
                  mimeType={originalPreviewMime}
                  filename={displayNameFromPath(current.path)}
                  loading={originalPreviewLoading}
                  error={originalPreviewError}
                  onDownload={download}
                  loadPdfInfo={loadPdfPreviewInfo ? () => loadPdfPreviewInfo(current.fileId, current.versionId) : undefined}
                  loadPdfPage={loadPdfPreviewPage ? (pageNumber) => loadPdfPreviewPage(current.fileId, pageNumber, current.versionId) : undefined}
                  loadPreviewSession={loadPreviewSession ? (clientOpenId, preferredMode) => loadPreviewSession(current.fileId, clientOpenId, preferredMode, current.versionId) : undefined}
                  refreshPreviewSession={refreshPreviewSession ? (accessToken, refreshToken, refreshContext) => refreshPreviewSession(current.fileId, accessToken, refreshToken, refreshContext) : undefined}
                  startFallbackPreview={startFallbackPreview ? () => startFallbackPreview(current.fileId, current.versionId) : undefined}
                  getFallbackPreview={getFallbackPreview ? () => getFallbackPreview(current.fileId, current.versionId) : undefined}
                  startSpreadsheetPreview={startSpreadsheetPreview ? () => startSpreadsheetPreview(current.fileId, current.versionId) : undefined}
                  getSpreadsheetPreview={getSpreadsheetPreview ? () => getSpreadsheetPreview(current.fileId, current.versionId) : undefined}
                  getSpreadsheetPage={getSpreadsheetPage ? (sheet, page) => getSpreadsheetPage(current.fileId, sheet, page, current.versionId) : undefined}
                />
              )}
              {binaryView === 'ai' && current.kind === 'parsed' && (
                <ParsedContentViewer content={current.content} onLink={navigate} />
              )}
              {binaryView === 'ai' && current.kind === 'binary' && (
                <div style={previewCenter}>
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={current.note} />
                  {onReparse && <Button type="primary" onClick={reparse}>重新解析</Button>}
                </div>
              )}
            </div>
          </div>
        )}
        {!editingText && !editingOffice && current?.kind === 'html-text' && (
          <div style={{ height: '100%', overflowY: 'auto', padding: '12px 16px', background: '#fafafa' }}>
            <Alert
              type="info"
              showIcon
              message="HTML 已按纯文本安全预览"
              description="为保护当前账号，工作空间中的 HTML 不会在平台域名下执行。"
              style={{ marginBottom: 12 }}
            />
            <pre
              data-testid="workspace-html-safe-preview"
              className="wb-pre"
              style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}
            >{current.content}</pre>
          </div>
        )}
        {!editingText && !editingOffice && current?.kind === 'image' && (
          <div key={refreshKey} style={{
            height: '100%', overflow: 'auto', display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            background: '#fafafa', padding: 16,
          }}>
            <img
              src={current.src}
              alt={current.path ?? ''}
              style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain', borderRadius: 4 }}
            />
          </div>
        )}
        {!editingText && !editingOffice && current?.kind === 'text' && (
          <div style={{ height: '100%', overflowY: 'auto', padding: '12px 16px', background: '#fafafa' }}>
            <pre className="wb-pre" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{current.content}</pre>
          </div>
        )}
        {!editingText && !editingOffice && current?.kind === 'unsupported' && (
          <div style={{ padding: 40, textAlign: 'center' }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={<>
                <div>{current.note ?? '暂不支持在浏览器内预览此资源'}</div>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>{current.href}</Typography.Text>
              </>} />
            {current.url && (
              <Button type="link" icon={<SelectOutlined />} onClick={openInNewTab}>在新标签页中打开</Button>
            )}
          </div>
        )}
      </div>
      <Modal
        open={versionsOpen}
        title="版本历史"
        footer={null}
        onCancel={() => setVersionsOpen(false)}
      >
        <List
          loading={versionsLoading}
          locale={{ emptyText: '暂无版本记录' }}
          dataSource={versions}
          renderItem={(version) => (
            <List.Item
              actions={[
                <Button key="copy" type="link" size="small" onClick={() => { void copyVersionAddress(version.id); }}>复制版本地址</Button>,
                ...(canRestoreCurrent && restoreFileVersion
                  ? [<Button key="restore" type="link" size="small" onClick={() => restoreVersion(version)}>恢复</Button>]
                  : []),
              ]}
            >
              <List.Item.Meta
                title={<span>版本 {version.version_no}{version.id === current?.file?.current_version_id && <Tag color="green" style={{ marginLeft: 8 }}>当前</Tag>}</span>}
                description={`${new Date(version.created_at).toLocaleString()} · ${version.size} B`}
              />
            </List.Item>
          )}
        />
      </Modal>
    </Drawer>
  );
}

const previewCenter: CSSProperties = {
  height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center',
  justifyContent: 'center', gap: 12, padding: 24, background: '#fafafa',
};

function navBtnStyle(disabled: boolean): CSSProperties {
  return {
    width: 30, height: 30, borderRadius: 8, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    background: disabled ? 'transparent' : WB.hover, color: disabled ? '#d1d5db' : '#4b5563',
    fontSize: 14, flex: '0 0 auto',
  };
}

export { classifyUrl, extOf };
export type { Source };
