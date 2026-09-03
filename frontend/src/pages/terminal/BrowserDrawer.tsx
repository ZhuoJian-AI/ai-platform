import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Drawer, Tooltip, Spin, Empty, Typography, Button, Input, Select, message, Segmented, Tag } from 'antd';
import {
  ArrowLeftOutlined, ArrowRightOutlined, ReloadOutlined, SelectOutlined,
  FileTextOutlined, GlobalOutlined, FileWordOutlined, FilePdfOutlined,
  FileImageOutlined, DownloadOutlined, ShareAltOutlined,
  ExportOutlined, FullscreenOutlined, FullscreenExitOutlined, SearchOutlined,
} from '@ant-design/icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import OriginalFilePreview, { supportsPagedWorkspacePreview } from '../../components/files/OriginalFilePreview';
import type {
  WorkspaceDownloadTicket, WorkspaceFallbackPreview, WorkspaceOriginalPreviewSource,
  WorkspacePdfPreviewInfo, WorkspacePreviewPreferredMode, WorkspacePreviewSession,
  WorkspaceSpreadsheetPage, WorkspaceSpreadsheetPreview,
} from '../../api/client';
// mammoth 仅在打开 .docx 时按需动态加载（见下方 useEffect），不进主包。

/** WorkBuddy 配色（与 Terminal.tsx 保持一致）。 */
const WB = {
  primary: '#6366F1', primaryHover: '#818CF8',
  border: '#E5E7EB', hover: '#EEF0F7',
};

const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

// ── 浏览器抽屉中可渲染的"源" ──────────────────────────────────────────────
// 每个源都携带原始 href，供地址栏展示与刷新时重新解析。
type Source =
  | { kind: 'web'; url: string; href: string }
  | { kind: 'pdf'; url: string; href: string }
  | { kind: 'docx'; url: string; href: string }
  | { kind: 'docx-bin'; content: string; path: string; href: string; fileId: string }
  | { kind: 'parsed'; content: string; originalContent: string; mime: string; path: string; href: string; fileId: string; parseKind: string | null }
  | { kind: 'binary'; content: string; mime: string; path: string; href: string; fileId: string; note: string }
  | { kind: 'image'; src: string; href: string; path?: string; fileId?: string }
  | { kind: 'md'; content: string; path: string; href: string; fileId: string }
  | { kind: 'html'; content: string; path: string; href: string; fileId: string }
  | { kind: 'text'; content: string; path: string; href: string; fileId: string }
  | { kind: 'unsupported'; href: string; url?: string; note?: string };

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif']);

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
export function classifyFile(f: {
  id: string; path: string; content: string | null;
  metadata?: Record<string, unknown> | null;
  extracted_text?: string | null; parse_status?: string; parse_kind?: string | null; parse_error?: string | null;
}): Source {
  const content = f.content ?? '';
  const ext = extOf(f.path);
  const meta = (f.metadata ?? {}) as { binary?: boolean; mime?: string };
  // 图片：二进制（base64）图片按 metadata.mime；无 metadata 时按扩展名兜底
  if (((meta.binary && (meta.mime || '').startsWith('image/')) || IMAGE_EXTS.has(ext)) && (!meta.binary || !!content)) {
    const mime = meta.mime || imgMimeOf(ext);
    return { kind: 'image', src: `data:${mime};base64,${content}`, href: f.path, path: f.path, fileId: f.id };
  }
  if (meta.binary && f.parse_status === 'ready' && f.extracted_text) {
    return {
      kind: 'parsed', content: f.extracted_text, originalContent: content,
      mime: meta.mime || 'application/octet-stream', path: f.path, href: f.path,
      fileId: f.id, parseKind: f.parse_kind ?? null,
    };
  }
  if (meta.binary) {
    return {
      kind: 'binary', content, mime: meta.mime || 'application/octet-stream',
      path: f.path, href: f.path, fileId: f.id,
      note: f.parse_error || '该文件尚未解析，可点击“重新解析”',
    };
  }
  if (ext === 'md' || ext === 'markdown') return { kind: 'md', content, path: f.path, href: f.path, fileId: f.id };
  // 二进制 .docx（base64 + metadata.binary）：客户端 mammoth 解析为 HTML 渲染，避免 base64 乱码。
  // .doc 旧格式 mammoth 不支持，仍走下面的 HTML/文本兜底。
  if (meta.binary && ext === 'docx') {
    return { kind: 'docx-bin', content, path: f.path, href: f.path, fileId: f.id };
  }
  // .doc/.docx/.html 等若内容是 HTML（agent 常把 HTML 存成 .doc 供 Word 打开），用 iframe srcDoc 渲染
  const looksHtml = /^\s*</.test(content.trim());
  if (['html', 'htm', 'doc', 'docx'].includes(ext) && looksHtml) {
    return { kind: 'html', content, path: f.path, href: f.path, fileId: f.id };
  }
  return { kind: 'text', content, path: f.path, href: f.path, fileId: f.id };
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
  initialHref: string | null;
  onClose: () => void;
  /** 把任意 href（http URL 或工作空间路径）解析为可渲染的 Source。 */
  resolveHref: (href: string) => Promise<Source>;
  onReparse?: (fileId: string) => Promise<void>;
  /** 鉴权获取未经转换的原始文件，由浏览器按实际格式选择查看器。 */
  loadOriginalPreview?: (fileId: string) => Promise<Blob>;
  /** 获取短时直连对象存储的预览源；历史文件会返回 blob 回退模式。 */
  loadOriginalPreviewSource?: (fileId: string) => Promise<WorkspaceOriginalPreviewSource>;
  /** 获取 PDF 原页信息与逐页图像，避免大文件完整下载后才开始预览。 */
  loadPdfPreviewInfo?: (fileId: string) => Promise<WorkspacePdfPreviewInfo>;
  loadPdfPreviewPage?: (fileId: string, pageNumber: number) => Promise<Blob>;
  /** 鉴权下载未经转换的原始文件。 */
  loadOriginalFile?: (fileId: string) => Promise<Blob>;
  /** 获取短时 OSS 直下载地址；下载字节不再经过 SaaS 后端。 */
  loadDownloadTicket?: (fileId: string) => Promise<WorkspaceDownloadTicket>;
  loadPreviewSession?: (fileId: string, clientOpenId: string, preferredMode?: WorkspacePreviewPreferredMode) => Promise<WorkspacePreviewSession>;
  refreshPreviewSession?: (fileId: string, accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  startFallbackPreview?: (fileId: string) => Promise<WorkspaceFallbackPreview>;
  getFallbackPreview?: (fileId: string) => Promise<WorkspaceFallbackPreview>;
  startSpreadsheetPreview?: (fileId: string) => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheetPreview?: (fileId: string) => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheetPage?: (fileId: string, sheet: string, page: number) => Promise<WorkspaceSpreadsheetPage>;
}

export default function BrowserDrawer({
  open, initialHref, onClose, resolveHref, onReparse, loadOriginalPreview,
  loadOriginalPreviewSource, loadPdfPreviewInfo, loadPdfPreviewPage, loadOriginalFile, loadDownloadTicket,
  loadPreviewSession, refreshPreviewSession, startFallbackPreview, getFallbackPreview,
  startSpreadsheetPreview, getSpreadsheetPreview, getSpreadsheetPage,
}: BrowserDrawerProps) {
  const [history, setHistory] = useState<Source[]>([]);
  const [index, setIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [binaryView, setBinaryView] = useState<'original' | 'ai'>('original');
  const [originalPreviewBlob, setOriginalPreviewBlob] = useState<Blob | null>(null);
  const [originalPreviewUrl, setOriginalPreviewUrl] = useState<string | null>(null);
  const [originalPreviewHeaders, setOriginalPreviewHeaders] = useState<Record<string, string>>({});
  const [originalPreviewMime, setOriginalPreviewMime] = useState<string | null>(null);
  const [originalPreviewError, setOriginalPreviewError] = useState<string | null>(null);
  const [originalPreviewLoading, setOriginalPreviewLoading] = useState(false);
  // 标记某次 resolve 是否由"刷新"触发——刷新失败时回退展示旧内容，避免清屏。
  const refreshTickRef = useRef(0);
  // index 的 ref 镜像：异步 navigate/refresh 完成后读取最新游标，避免闭包 stale 值。
  const indexRef = useRef(-1);
  useEffect(() => { indexRef.current = index; }, [index]);

  // 每次关闭预览后恢复为侧边抽屉，避免下次打开时意外占满屏幕。
  useEffect(() => {
    if (!open) setIsFullscreen(false);
  }, [open]);

  // 二进制 .docx → HTML 的客户端转换结果。current 切换或刷新时重算。
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [docxError, setDocxError] = useState<string | null>(null);

  const current = index >= 0 ? history[index] : null;
  const canBack = index > 0;
  const canForward = index >= 0 && index < history.length - 1;

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
        const source = await loadOriginalPreviewSource(current.fileId);
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
      const blob = await loadOriginalPreview(current.fileId);
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

  // 解析并压入历史栈（清掉前进部分），用于初始打开与点击内部链接。
  const navigate = useCallback(async (href: string) => {
    setLoading(true);
    let src: Source;
    try {
      src = await resolveHref(href);
    } catch {
      src = { kind: 'unsupported', href, note: '无法加载该资源' };
    }
    setLoading(false);
    // 用 indexRef 读取完成时刻的最新游标，正确截断前进历史。
    const at = indexRef.current;
    setHistory((h) => [...h.slice(0, at + 1), src]);
    setIndex(at + 1);
    setRefreshKey((k) => k + 1);
  }, [resolveHref]);

  // initialHref 变化且抽屉打开 → 重置历史并导航到新源
  useEffect(() => {
    if (open && initialHref) {
      setHistory([]);
      setIndex(-1);
      indexRef.current = -1;
      navigate(initialHref);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialHref, open]);

  const goBack = () => { if (canBack) { setIndex((i) => i - 1); setRefreshKey((k) => k + 1); } };
  const goForward = () => { if (canForward) { setIndex((i) => i + 1); setRefreshKey((k) => k + 1); } };

  // 刷新：URL 类直接重载 iframe；文件类重新解析当前 href
  const refresh = async () => {
    if (!current) return;
    if (current.kind === 'web' || current.kind === 'pdf' || current.kind === 'docx') {
      setRefreshKey((k) => k + 1);
      return;
    }
    // md/text/unsupported：重新解析当前 href 覆盖当前栈顶
    refreshTickRef.current += 1;
    const tick = refreshTickRef.current;
    setLoading(true);
    let src: Source;
    try { src = await resolveHref(current.href); }
    catch { src = { kind: 'unsupported', href: current.href, note: '无法加载该资源' }; }
    if (tick !== refreshTickRef.current) return; // 已被更新的刷新覆盖
    setLoading(false);
    const at = indexRef.current;
    setHistory((h) => { const n = [...h]; n[at] = src; return n; });
    setRefreshKey((k) => k + 1);
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
    if (current.kind === 'md' || current.kind === 'text' || current.kind === 'html') {
      const ext = extOf(current.path);
      const mime = ext === 'md' ? 'text/markdown' : ext === 'html' || ext === 'htm' || ext === 'doc' || ext === 'docx' ? 'text/html' : 'text/plain';
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
    if (current.kind === 'md' || current.kind === 'text' || current.kind === 'html') {
      const ext = extOf(current.path);
      const mime = ext === 'md' ? 'text/markdown'
        : (['html', 'htm', 'doc', 'docx'].includes(ext) ? 'text/html' : 'text/plain');
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
          const ticket = await loadDownloadTicket(current.fileId);
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
          ? await loadOriginalFile(current.fileId)
          : new Blob([b64ToUint8(current.kind === 'parsed' ? current.originalContent : current.content)], { type: current.mime });
        saveBlob(blob, displayNameFromPath(current.path));
      } catch (error) {
        if (error && (error as { status?: number }).status === 409 && loadOriginalFile) {
          try {
            const blob = await loadOriginalFile(current.fileId);
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

  // 分享：仅对 HTML 工作空间文件，生成免登录永久公开访问链接并复制到剪贴板
  const share = async () => {
    if (!current || current.kind !== 'html' || !current.fileId) return;
    const url = `${window.location.origin}/api/v1/terminal/public/files/${current.fileId}`;
    try {
      await navigator.clipboard.writeText(url);
      message.success('分享链接已复制到剪贴板');
    } catch {
      // 剪贴板被拒（如非 https）：降级弹窗展示链接供手动复制
      message.info(url, 0);
    }
  };

  const canShare = current?.kind === 'html' && !!current.fileId;

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
  const addr = current?.kind === 'web' || current?.kind === 'pdf' || current?.kind === 'docx'
    ? rawAddr
    : (rawAddr ? displayNameFromPath(rawAddr) : '');
  const addrIcon =
    current?.kind === 'web' ? <GlobalOutlined /> :
    current?.kind === 'pdf' ? <FilePdfOutlined /> :
    current?.kind === 'docx' || current?.kind === 'docx-bin' ? <FileWordOutlined /> :
    current?.kind === 'image' ? <FileImageOutlined /> :
    current?.kind === 'md' || current?.kind === 'text' || current?.kind === 'html' || current?.kind === 'parsed' || current?.kind === 'binary' ? <FileTextOutlined /> :
    <SelectOutlined />;

  return (
    <Drawer
      placement="right"
      open={open}
      width={isFullscreen ? '100vw' : 'min(760px, 100vw)'}
      onClose={onClose}
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
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{addr || 'about:blank'}</span>
        </div>
        {navBtn(download, false, <DownloadOutlined />, '下载')}
        {canShare && navBtn(share, false, <ShareAltOutlined />, '生成分享链接')}
        {navBtn(
          () => setIsFullscreen((value) => !value),
          false,
          isFullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />,
          isFullscreen ? '退出全屏预览' : '全屏预览',
        )}
        {navBtn(openInNewTab, false, <ExportOutlined />, '在新标签页中打开')}
        <Button size="small" type="text" onClick={onClose} style={{ color: '#6b7280' }}>关闭</Button>
      </div>

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
        {current?.kind === 'web' && (
          <iframe key={refreshKey} src={current.url} title="web"
            style={{ width: '100%', height: '100%', border: 'none' }}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox" />
        )}
        {current?.kind === 'pdf' && (
          <iframe key={refreshKey} src={current.url} title="pdf"
            style={{ width: '100%', height: '100%', border: 'none' }} />
        )}
        {current?.kind === 'docx' && (
          <iframe key={refreshKey} src={gviewUrl(current.url)} title="docx"
            style={{ width: '100%', height: '100%', border: 'none' }} />
        )}
        {current?.kind === 'docx-bin' && (
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
        {current?.kind === 'md' && (
          <div className="wb-md" style={{ height: '100%', overflowY: 'auto', padding: '20px 24px' }}>
            <MdNav content={current.content} onLink={navigate} />
          </div>
        )}
        {(current?.kind === 'parsed' || current?.kind === 'binary') && (
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
                  loadPdfInfo={loadPdfPreviewInfo ? () => loadPdfPreviewInfo(current.fileId) : undefined}
                  loadPdfPage={loadPdfPreviewPage ? (pageNumber) => loadPdfPreviewPage(current.fileId, pageNumber) : undefined}
                  loadPreviewSession={loadPreviewSession ? (clientOpenId, preferredMode) => loadPreviewSession(current.fileId, clientOpenId, preferredMode) : undefined}
                  refreshPreviewSession={refreshPreviewSession ? (accessToken, refreshToken, refreshContext) => refreshPreviewSession(current.fileId, accessToken, refreshToken, refreshContext) : undefined}
                  startFallbackPreview={startFallbackPreview ? () => startFallbackPreview(current.fileId) : undefined}
                  getFallbackPreview={getFallbackPreview ? () => getFallbackPreview(current.fileId) : undefined}
                  startSpreadsheetPreview={startSpreadsheetPreview ? () => startSpreadsheetPreview(current.fileId) : undefined}
                  getSpreadsheetPreview={getSpreadsheetPreview ? () => getSpreadsheetPreview(current.fileId) : undefined}
                  getSpreadsheetPage={getSpreadsheetPage ? (sheet, page) => getSpreadsheetPage(current.fileId, sheet, page) : undefined}
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
        {current?.kind === 'html' && (
          <iframe key={refreshKey} srcDoc={current.content} title="doc"
            style={{ width: '100%', height: '100%', border: 'none' }}
            sandbox="allow-same-origin allow-popups" />
        )}
        {current?.kind === 'image' && (
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
        {current?.kind === 'text' && (
          <div style={{ height: '100%', overflowY: 'auto', padding: '12px 16px', background: '#fafafa' }}>
            <pre className="wb-pre" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{current.content}</pre>
          </div>
        )}
        {current?.kind === 'unsupported' && (
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
