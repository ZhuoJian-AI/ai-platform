import { lazy, Suspense, useEffect, useMemo, useState, type CSSProperties } from 'react';
import { Button, Empty, Spin, Typography } from 'antd';
import { DownloadOutlined } from '@ant-design/icons';

const OfficeFilePreview = lazy(() => import('./OfficeFilePreview'));

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

function extensionOf(filename: string): string {
  const index = filename.lastIndexOf('.');
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : '';
}

export interface OriginalFilePreviewProps {
  blob: Blob | null;
  filename: string;
  loading?: boolean;
  error?: string | null;
  onDownload: () => void;
}

/**
 * Render the authenticated original Blob with the viewer appropriate for its
 * actual file type. Office files stay Office files; they are never converted
 * to a paginated PDF merely for browser display.
 */
export default function OriginalFilePreview({
  blob, filename, loading = false, error, onDownload,
}: OriginalFilePreviewProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [textError, setTextError] = useState<string | null>(null);
  const extension = extensionOf(filename);

  const originalFile = useMemo(() => {
    if (!blob) return null;
    return new File([blob], filename, {
      type: blob.type || 'application/octet-stream',
      lastModified: Date.now(),
    });
  }, [blob, filename]);

  useEffect(() => {
    if (!blob) {
      setObjectUrl(null);
      return;
    }
    const url = URL.createObjectURL(blob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [blob]);

  useEffect(() => {
    setTextContent(null);
    setTextError(null);
    if (!blob || !(TEXT_EXTENSIONS.has(extension) || blob.type.startsWith('text/'))) return;
    let cancelled = false;
    blob.text()
      .then((value) => { if (!cancelled) setTextContent(value); })
      .catch((reason) => { if (!cancelled) setTextError((reason as Error)?.message || '文本读取失败'); });
    return () => { cancelled = true; };
  }, [blob, extension]);

  if (loading) return <LoadingState label="正在读取原文件…" />;
  if (!blob || !originalFile) {
    return (
      <div style={centerStyle}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={error || '原文件暂时无法读取'} />
        <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
      </div>
    );
  }

  if (OFFICE_EXTENSIONS.has(extension)) {
    return (
      <Suspense fallback={<LoadingState label="正在加载 Office 查看器…" />}>
        <OfficeFilePreview file={originalFile} filename={filename} extension={extension} />
      </Suspense>
    );
  }

  if ((extension === 'pdf' || blob.type === 'application/pdf') && objectUrl) {
    return <iframe title={filename} src={objectUrl} style={frameStyle} />;
  }

  if ((IMAGE_EXTENSIONS.has(extension) || blob.type.startsWith('image/')) && objectUrl) {
    return (
      <div style={centerStyle}>
        <img src={objectUrl} alt={filename} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} />
      </div>
    );
  }

  if ((VIDEO_EXTENSIONS.has(extension) || blob.type.startsWith('video/')) && objectUrl) {
    return <div style={centerStyle}><video controls src={objectUrl} style={{ maxWidth: '100%', maxHeight: '100%' }} /></div>;
  }

  if ((AUDIO_EXTENSIONS.has(extension) || blob.type.startsWith('audio/')) && objectUrl) {
    return <div style={centerStyle}><audio controls src={objectUrl} style={{ width: 'min(560px, 90%)' }} /></div>;
  }

  if (TEXT_EXTENSIONS.has(extension) || blob.type.startsWith('text/')) {
    if (textError) return <div style={centerStyle}><Empty description={textError} /></div>;
    if (textContent === null) return <LoadingState label="正在读取文本…" />;
    return (
      <div style={{ height: '100%', overflow: 'auto', padding: '16px 20px', background: '#fafafa' }}>
        <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'Consolas, monospace' }}>{textContent}</pre>
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

const frameStyle: CSSProperties = { width: '100%', height: '100%', border: 'none', background: '#fff' };
