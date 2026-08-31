import { useEffect, useRef, useState } from 'react';
import { Button, Empty, Progress, Spin, Typography } from 'antd';
import {
  DownloadOutlined, LeftOutlined, RightOutlined, ZoomInOutlined, ZoomOutOutlined,
} from '@ant-design/icons';
import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type RenderTask } from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

// The first production response for this worker was cached with the legacy
// application/octet-stream MIME type. Keep an explicit loader revision in the
// URL so existing browsers refetch it after the server MIME fix instead of
// reusing that immutable response.
GlobalWorkerOptions.workerSrc = `${pdfWorkerUrl}?loader=2`;

export interface PdfFilePreviewProps {
  file?: File;
  url?: string;
  filename: string;
  onDownload: () => void;
}

/**
 * Demand-driven PDF preview. Only the current page is decoded and painted;
 * PDF.js asks OSS for byte ranges as the user navigates. This makes the first
 * page of a large PDF visible without waiting for every page to be parsed.
 */
export default function PdfFilePreview({ file, url, filename, onDownload }: PdfFilePreviewProps) {
  const urlIdentity = url?.split('?', 1)[0] || '';
  const stableUrlRef = useRef<{ identity: string; url?: string }>({ identity: urlIdentity, url });
  if (stableUrlRef.current.identity !== urlIdentity || (!stableUrlRef.current.url && url)) {
    stableUrlRef.current = { identity: urlIdentity, url };
  }
  const stableUrl = stableUrlRef.current.url;
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const stageRef = useRef<HTMLDivElement | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const [documentProxy, setDocumentProxy] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [loadProgress, setLoadProgress] = useState(0);
  const [pageLoading, setPageLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    setDocumentProxy(null);
    setPageNumber(1);
    setZoom(1);
    setLoadProgress(0);
    setError(null);
    if (!stableUrl && !file) return;

    const load = async () => {
      const source = stableUrl
        ? {
          url: stableUrl,
          rangeChunkSize: 512 * 1024,
          disableAutoFetch: true,
          disableStream: false,
        }
        : { data: await file!.arrayBuffer() };
      if (disposed) return;
      const task = getDocument(source);
      task.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
        if (!disposed && total > 0) setLoadProgress(Math.min(100, Math.round((loaded / total) * 100)));
      };
      try {
        const nextDocument = await task.promise;
        if (disposed) {
          await nextDocument.destroy();
          return;
        }
        setDocumentProxy(nextDocument);
        setLoadProgress(100);
      } catch (reason) {
        if (!disposed) setError((reason as Error)?.message || 'PDF 读取失败');
      }
    };
    void load();
    return () => {
      disposed = true;
      renderTaskRef.current?.cancel();
    };
  }, [file, stableUrl]);

  useEffect(() => {
    if (!documentProxy || !canvasRef.current || !stageRef.current) return;
    let disposed = false;
    setPageLoading(true);
    const render = async () => {
      try {
        const page = await documentProxy.getPage(pageNumber);
        if (disposed || !canvasRef.current || !stageRef.current) return;
        const initial = page.getViewport({ scale: 1 });
        const availableWidth = Math.max(320, stageRef.current.clientWidth - 36);
        const fitScale = Math.min(2, availableWidth / initial.width);
        const viewport = page.getViewport({ scale: fitScale * zoom });
        const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
        const canvas = canvasRef.current;
        const context = canvas.getContext('2d', { alpha: false });
        if (!context) throw new Error('浏览器无法创建 PDF 画布');
        canvas.width = Math.floor(viewport.width * pixelRatio);
        canvas.height = Math.floor(viewport.height * pixelRatio);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;
        const task = page.render({
          canvas,
          canvasContext: context,
          viewport,
          transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
        });
        renderTaskRef.current = task;
        await task.promise;
      } catch (reason) {
        if (!disposed && (reason as Error)?.name !== 'RenderingCancelledException') {
          setError((reason as Error)?.message || 'PDF 页面渲染失败');
        }
      } finally {
        if (!disposed) setPageLoading(false);
      }
    };
    void render();
    return () => {
      disposed = true;
      renderTaskRef.current?.cancel();
    };
  }, [documentProxy, pageNumber, zoom]);

  useEffect(() => () => {
    void documentProxy?.destroy();
  }, [documentProxy]);

  if (error) {
    return (
      <div style={centerStyle}>
        <Empty description={`PDF 预览失败：${error}`} />
        <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
      </div>
    );
  }

  return (
    <div data-testid="pdf-preview" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#eef1f5' }}>
      <div style={{ height: 46, flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#fff', borderBottom: '1px solid #dfe4ea', gap: 12 }}>
        <Typography.Text ellipsis title={filename} style={{ maxWidth: 320 }}>{filename}</Typography.Text>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Button size="small" icon={<LeftOutlined />} disabled={!documentProxy || pageNumber <= 1} onClick={() => setPageNumber((value) => Math.max(1, value - 1))} />
          <Typography.Text style={{ minWidth: 78, textAlign: 'center', fontSize: 12 }}>
            {documentProxy ? `${pageNumber} / ${documentProxy.numPages}` : '读取中'}
          </Typography.Text>
          <Button size="small" icon={<RightOutlined />} disabled={!documentProxy || pageNumber >= documentProxy.numPages} onClick={() => setPageNumber((value) => Math.min(documentProxy?.numPages || value, value + 1))} />
          <Button size="small" icon={<ZoomOutOutlined />} disabled={zoom <= 0.6} onClick={() => setZoom((value) => Math.max(0.6, value - 0.2))} />
          <Typography.Text style={{ minWidth: 40, textAlign: 'center', fontSize: 12 }}>{Math.round(zoom * 100)}%</Typography.Text>
          <Button size="small" icon={<ZoomInOutlined />} disabled={zoom >= 2.4} onClick={() => setZoom((value) => Math.min(2.4, value + 0.2))} />
          <Button size="small" icon={<DownloadOutlined />} onClick={onDownload}>下载</Button>
        </div>
      </div>
      {!documentProxy && (
        <div style={{ padding: '8px 18px 0', background: '#fff' }}>
          <Progress percent={loadProgress} size="small" status="active" format={(value) => `正在读取首屏 ${value || 0}%`} />
        </div>
      )}
      <div ref={stageRef} style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 18, textAlign: 'center', position: 'relative' }}>
        {!documentProxy && <div style={centerStyle}><Spin /><Typography.Text type="secondary">正在按需读取 PDF，首屏会优先显示…</Typography.Text></div>}
        <canvas ref={canvasRef} style={{ display: documentProxy ? 'inline-block' : 'none', background: '#fff', boxShadow: '0 4px 20px rgba(15,23,42,.16)' }} />
        {documentProxy && pageLoading && <Spin style={{ position: 'absolute', top: 28, right: 28 }} />}
      </div>
    </div>
  );
}

const centerStyle: React.CSSProperties = {
  width: '100%', height: '100%', minHeight: 220, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24,
};
