import { lazy, Suspense, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Button, Empty, Spin, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';
import type { WorkspaceFallbackPreview, WorkspacePdfPreviewInfo, WorkspacePreviewSession } from '../../api/client';
import WorkspacePreviewSessionView from './WorkspacePreviewSessionView';

const OfficeFilePreview = lazy(() => import('./OfficeFilePreview'));
const PdfFilePreview = lazy(() => import('./PdfFilePreview'));

const OFFICE_EXTENSIONS = new Set([
  'doc', 'docx', 'docm', 'dot', 'dotx', 'dotm', 'rtf', 'odt',
  'xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'xltm', 'ods', 'csv', 'tsv',
  'ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'ppsm', 'pot', 'potx', 'potm', 'odp',
]);
const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif']);
const TEXT_EXTENSIONS = new Set([
  'txt', 'md', 'markdown', 'json', 'xml', 'yaml', 'yml', 'log', 'ini', 'conf',
  'css', 'js', 'jsx', 'ts', 'tsx', 'py', 'java', 'sql', 'sh', 'bat', 'ps1',
]);
const VIDEO_EXTENSIONS = new Set(['mp4', 'webm', 'ogg', 'mov', 'm4v']);
const AUDIO_EXTENSIONS = new Set(['mp3', 'wav', 'ogg', 'm4a', 'aac', 'flac']);
const EMPTY_HEADERS: Record<string, string> = {};

function extensionOf(filename: string): string {
  const index = filename.lastIndexOf('.');
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : '';
}

export function supportsPagedWorkspacePreview(filename: string): boolean {
  const extension = extensionOf(filename);
  return extension === 'pdf' || OFFICE_EXTENSIONS.has(extension);
}

export interface OriginalFilePreviewProps {
  blob: Blob | null;
  sourceUrl?: string | null;
  sourceHeaders?: Record<string, string>;
  mimeType?: string | null;
  filename: string;
  loading?: boolean;
  error?: string | null;
  onDownload: () => void;
  loadPdfInfo?: () => Promise<WorkspacePdfPreviewInfo>;
  loadPdfPage?: (pageNumber: number) => Promise<Blob>;
  loadPreviewSession?: () => Promise<WorkspacePreviewSession>;
  refreshPreviewSession?: (accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  startFallbackPreview?: () => Promise<WorkspaceFallbackPreview>;
  getFallbackPreview?: () => Promise<WorkspaceFallbackPreview>;
}

/**
 * Render the authenticated original file with the viewer appropriate for its
 * type. Office downloads remain byte-for-byte original; their visual preview
 * uses a server-generated, revision-keyed PDF cache so browsers do not parse
 * the complete Office package on every open.
 */
export default function OriginalFilePreview({
  loadPreviewSession, refreshPreviewSession, startFallbackPreview, getFallbackPreview, ...legacyProps
}: OriginalFilePreviewProps) {
  if (loadPreviewSession && refreshPreviewSession && startFallbackPreview && getFallbackPreview) {
    return (
      <WorkspacePreviewSessionView
        filename={legacyProps.filename}
        onDownload={legacyProps.onDownload}
        loadSession={loadPreviewSession}
        refreshSession={refreshPreviewSession}
        startFallback={startFallbackPreview}
        getFallback={getFallbackPreview}
      />
    );
  }
  return <LegacyOriginalFilePreview {...legacyProps} />;
}

function LegacyOriginalFilePreview({
  blob, sourceUrl, sourceHeaders = EMPTY_HEADERS, mimeType, filename, loading = false, error, onDownload,
  loadPdfInfo, loadPdfPage,
}: Omit<OriginalFilePreviewProps, 'loadPreviewSession' | 'refreshPreviewSession' | 'startFallbackPreview' | 'getFallbackPreview'>) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [remoteBlob, setRemoteBlob] = useState<Blob | null>(null);
  const [remoteLoading, setRemoteLoading] = useState(false);
  const [remoteError, setRemoteError] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textError, setTextError] = useState<string | null>(null);
  const extension = extensionOf(filename);
  const hasPagedServerPreview = supportsPagedWorkspacePreview(filename) && !!loadPdfInfo && !!loadPdfPage;
  const hasSourceHeaders = Object.keys(sourceHeaders).length > 0;
  // Signed OSS URLs can be handed directly to the Office renderer.  Fetching
  // them into React state first adds a full-file memory copy and, for larger
  // presentations, can leave the outer loading state waiting even though OSS
  // has already completed the response.  Header-authenticated legacy sources
  // still need the Blob fallback.
  const needsRemoteBlob = TEXT_EXTENSIONS.has(extension) || hasSourceHeaders;
  const effectiveBlob = blob || remoteBlob;
  const blobMime = effectiveBlob?.type || '';
  const effectiveMime = !blobMime || blobMime === 'application/octet-stream'
    ? (mimeType || blobMime)
    : blobMime;
  const directUrl = sourceUrl && !hasSourceHeaders ? sourceUrl : null;

  useEffect(() => {
    setRemoteBlob(null);
    setRemoteError(null);
    if (!sourceUrl || !needsRemoteBlob || blob) return;
    const controller = new AbortController();
    setRemoteLoading(true);
    fetch(sourceUrl, { headers: sourceHeaders, signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`原文件读取失败（HTTP ${response.status}）`);
        return response.blob();
      })
      .then((value) => setRemoteBlob(value))
      .catch((reason) => {
        if ((reason as Error).name !== 'AbortError') {
          setRemoteError((reason as Error)?.message || '原文件读取失败');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setRemoteLoading(false);
      });
    return () => controller.abort();
  }, [blob, needsRemoteBlob, sourceHeaders, sourceUrl]);

  const originalFile = useMemo(() => {
    if (!effectiveBlob) return null;
    return new File([effectiveBlob], filename, {
      type: effectiveMime || 'application/octet-stream',
      lastModified: Date.now(),
    });
  }, [effectiveBlob, effectiveMime, filename]);

  useEffect(() => {
    if (!effectiveBlob) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(effectiveBlob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [effectiveBlob]);

  useEffect(() => {
    setTextContent(null);
    setTextError(null);
    if (!effectiveBlob || !(TEXT_EXTENSIONS.has(extension) || effectiveMime.startsWith('text/'))) return;
    let cancelled = false;
    effectiveBlob.text()
      .then((value) => { if (!cancelled) setTextContent(value); })
      .catch((reason) => { if (!cancelled) setTextError((reason as Error)?.message || '文本读取失败'); });
    return () => { cancelled = true; };
  }, [effectiveBlob, effectiveMime, extension]);

  if ((loading || remoteLoading) && !hasPagedServerPreview) {
    return <LoadingState label="正在从对象存储读取原文件…" />;
  }

  const previewUrl = directUrl || objectUrl;

  // Workspace PDF/Office previews are already revision-keyed and page-driven.
  // Prefer that cache before requesting the complete original file so reopening
  // never competes with a large background download for browser connections.
  if (hasPagedServerPreview) {
    return (
      <Suspense fallback={<LoadingState label="正在加载版式缓存…" />}>
        <PdfFilePreview
          filename={filename}
          onDownload={onDownload}
          loadInfo={loadPdfInfo}
          loadPage={loadPdfPage}
          previewLabel={extension === 'pdf' ? '原页缓存' : '版式缓存'}
        />
      </Suspense>
    );
  }

  // PDFs without a workspace page cache use the dedicated PDF.js renderer.
  if ((extension === 'pdf' || effectiveMime === 'application/pdf') && (originalFile || directUrl)) {
    return (
      <Suspense fallback={<LoadingState label="正在加载 PDF 查看器…" />}>
        <PdfFilePreview
          file={originalFile || undefined}
          url={directUrl || undefined}
          filename={filename}
          onDownload={onDownload}
          loadInfo={loadPdfInfo}
          loadPage={loadPdfPage}
        />
      </Suspense>
    );
  }

  if ((IMAGE_EXTENSIONS.has(extension) || effectiveMime.startsWith('image/')) && previewUrl) {
    return (
      <div style={centerStyle}>
        <img src={previewUrl} alt={filename} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
      </div>
    );
  }

  if ((VIDEO_EXTENSIONS.has(extension) || effectiveMime.startsWith('video/')) && previewUrl) {
    return <div style={centerStyle}><video controls src={previewUrl} style={{ maxWidth: '100%', maxHeight: '100%' }} /></div>;
  }

  if ((AUDIO_EXTENSIONS.has(extension) || effectiveMime.startsWith('audio/')) && previewUrl) {
    return <div style={centerStyle}><audio controls src={previewUrl} style={{ width: 'min(560px, 90%)' }} /></div>;
  }

  if (OFFICE_EXTENSIONS.has(extension) && (originalFile || directUrl)) {
    return (
      <Suspense fallback={<LoadingState label="正在加载 Office 查看器…" />}>
        <OfficeFilePreview
          file={originalFile || undefined}
          url={directUrl || undefined}
          filename={filename}
          extension={extension}
          onDownload={onDownload}
        />
      </Suspense>
    );
  }

  if (TEXT_EXTENSIONS.has(extension) || effectiveMime.startsWith('text/')) {
    if (textError) return <div style={centerStyle}><Empty description={textError} /></div>;
    if (textContent === null) return <LoadingState label="正在读取文本…" />;
    return (
      <div style={{ height: '100%', overflow: 'auto', padding: '16px 20px', background: '#fafafa' }}>
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'Consolas, monospace' }}>{textContent}</pre>
      </div>
    );
  }

  if (!effectiveBlob || !originalFile) {
    return (
      <div style={centerStyle}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={remoteError || error || '原文件暂时无法读取'} />
        <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
      </div>
    );
  }

  return (
    <div style={centerStyle}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该格式暂无浏览器原生查看器，原文件没有被转换或修改" />
      <Typography.Text type="secondary">{filename}</Typography.Text>
      <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <div style={centerStyle}>
      <Spin />
      <Typography.Text type="secondary">{label}</Typography.Text>
    </div>
  );
}

const centerStyle: CSSProperties = {
  width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24, background: '#fafafa',
};
