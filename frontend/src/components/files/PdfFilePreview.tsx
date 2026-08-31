import { useEffect, useRef, useState } from 'react';
import { Button, Empty, Progress, Spin, Typography } from 'antd';
import { DownloadOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons';
import {
  GlobalWorkerOptions, getDocument, type PDFDocumentProxy, type PDFPageProxy, type RenderTask,
} from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

// Force browsers that cached the worker with the old MIME type to refetch it.
GlobalWorkerOptions.workerSrc = `${pdfWorkerUrl}?loader=2`;

export interface PdfFilePreviewProps {
  file?: File;
  url?: string;
  filename: string;
  onDownload: () => void;
}

/** Show the original PDF pages continuously; nearby pages render progressively. */
export default function PdfFilePreview({ file, url, filename, onDownload }: PdfFilePreviewProps) {
  const urlIdentity = url?.split('?', 1)[0] || '';
  const stableUrlRef = useRef<{ identity: string; url?: string }>({ identity: urlIdentity, url });
  if (stableUrlRef.current.identity !== urlIdentity || (!stableUrlRef.current.url && url)) {
    stableUrlRef.current = { identity: urlIdentity, url };
  }
  const stableUrl = stableUrlRef.current.url;
  const stageRef = useRef<HTMLDivElement | null>(null);
  const [documentProxy, setDocumentProxy] = useState<PDFDocumentProxy | null>(null);
  const [stageWidth, setStageWidth] = useState(900);
  const [zoom, setZoom] = useState(1);
  const [loadProgress, setLoadProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const update = () => setStageWidth(Math.max(360, stage.clientWidth));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(stage);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let disposed = false;
    let loadedDocument: PDFDocumentProxy | null = null;
    setDocumentProxy(null);
    setZoom(1);
    setLoadProgress(0);
    setError(null);
    if (!stableUrl && !file) return;

    const load = async () => {
      const source = stableUrl
        ? {
          url: stableUrl,
          rangeChunkSize: 1024 * 1024,
          // A page tree may live near EOF. Auto-fetch must stay enabled or a
          // valid large PDF can stop at 100% network progress before opening.
          disableStream: false,
          disableAutoFetch: false,
        }
        : { data: await file!.arrayBuffer() };
      if (disposed) return;
      const task = getDocument(source);
      task.onProgress = ({ loaded, total }: { loaded: number; total: number }) => {
        if (!disposed && total > 0) setLoadProgress(Math.min(100, Math.round((loaded / total) * 100)));
      };
      try {
        loadedDocument = await task.promise;
        if (disposed) {
          await loadedDocument.destroy();
          return;
        }
        setDocumentProxy(loadedDocument);
        setLoadProgress(100);
      } catch (reason) {
        if (!disposed) setError((reason as Error)?.message || 'PDF 读取失败');
      }
    };
    void load();
    return () => {
      disposed = true;
      if (loadedDocument) void loadedDocument.destroy();
    };
  }, [file, stableUrl]);

  if (error) {
    return (
      <div style={centerStyle}>
        <Empty description={`PDF 预览失败：${error}`} />
        <Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
      </div>
    );
  }

  return (
    <div data-testid="pdf-preview" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#e8ebef' }}>
      <div style={{ minHeight: 46, flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#fff', borderBottom: '1px solid #dfe4ea', gap: 12 }}>
        <Typography.Text ellipsis title={filename} style={{ maxWidth: 360 }}>{filename}</Typography.Text>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {documentProxy ? `共 ${documentProxy.numPages} 页 · 连续原页预览` : '正在读取原文件'}
          </Typography.Text>
          <Button size="small" icon={<ZoomOutOutlined />} disabled={zoom <= 0.6} onClick={() => setZoom((value) => Math.max(0.6, value - 0.2))} />
          <Typography.Text style={{ minWidth: 42, textAlign: 'center', fontSize: 12 }}>{Math.round(zoom * 100)}%</Typography.Text>
          <Button size="small" icon={<ZoomInOutlined />} disabled={zoom >= 2.4} onClick={() => setZoom((value) => Math.min(2.4, value + 0.2))} />
          <Button size="small" icon={<DownloadOutlined />} onClick={onDownload}>下载</Button>
        </div>
      </div>
      {!documentProxy && (
        <div style={{ padding: '8px 18px 0', background: '#fff' }}>
          <Progress percent={loadProgress} size="small" status="active" format={(value) => `读取原文件 ${value || 0}%`} />
        </div>
      )}
      <div ref={stageRef} style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: '20px 18px 40px' }}>
        {!documentProxy ? (
          <div style={centerStyle}><Spin /><Typography.Text type="secondary">正在读取完整 PDF…</Typography.Text></div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18 }}>
            {Array.from({ length: documentProxy.numPages }, (_, index) => (
              <PdfPageCanvas
                key={index + 1}
                documentProxy={documentProxy}
                pageNumber={index + 1}
                stageWidth={stageWidth}
                zoom={zoom}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function PdfPageCanvas({
  documentProxy, pageNumber, stageWidth, zoom,
}: {
  documentProxy: PDFDocumentProxy;
  pageNumber: number;
  stageWidth: number;
  zoom: number;
}) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const renderTaskRef = useRef<RenderTask | null>(null);
  const pageRef = useRef<PDFPageProxy | null>(null);
  const [nearViewport, setNearViewport] = useState(pageNumber <= 2);
  const [aspectRatio, setAspectRatio] = useState(1 / Math.sqrt(2));
  const [rendering, setRendering] = useState(false);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) setNearViewport(true);
    }, { rootMargin: '1000px 0px' });
    observer.observe(host);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!nearViewport || !canvasRef.current) return;
    let disposed = false;
    setRendering(true);
    const render = async () => {
      const page = pageRef.current || await documentProxy.getPage(pageNumber);
      pageRef.current = page;
      if (disposed || !canvasRef.current) return;
      const original = page.getViewport({ scale: 1 });
      setAspectRatio(original.width / original.height);
      const availableWidth = Math.min(1500, Math.max(320, stageWidth - 64));
      const fitScale = availableWidth / original.width;
      const viewport = page.getViewport({ scale: fitScale * zoom });
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      const canvas = canvasRef.current;
      canvas.width = Math.floor(viewport.width * pixelRatio);
      canvas.height = Math.floor(viewport.height * pixelRatio);
      canvas.style.width = `${Math.floor(viewport.width)}px`;
      canvas.style.height = `${Math.floor(viewport.height)}px`;
      renderTaskRef.current?.cancel();
      const task = page.render({
        canvas,
        viewport,
        transform: pixelRatio === 1 ? undefined : [pixelRatio, 0, 0, pixelRatio, 0, 0],
      });
      renderTaskRef.current = task;
      await task.promise;
    };
    void render()
      .catch((reason) => {
        if (!disposed && (reason as Error)?.name !== 'RenderingCancelledException') {
          // Keep the page placeholder; the document-level download remains usable.
        }
      })
      .finally(() => { if (!disposed) setRendering(false); });
    return () => {
      disposed = true;
      renderTaskRef.current?.cancel();
    };
  }, [documentProxy, nearViewport, pageNumber, stageWidth, zoom]);

  const placeholderWidth = Math.min(1500, Math.max(320, stageWidth - 64)) * zoom;
  const placeholderHeight = placeholderWidth / aspectRatio;
  return (
    <div
      ref={hostRef}
      data-testid={`pdf-page-${pageNumber}`}
      style={{ position: 'relative', width: placeholderWidth, minHeight: placeholderHeight, background: '#fff', boxShadow: '0 4px 20px rgba(15,23,42,.16)' }}
    >
      <canvas ref={canvasRef} style={{ display: nearViewport ? 'block' : 'none', background: '#fff' }} />
      {rendering && <Spin style={{ position: 'absolute', top: 18, right: 18 }} />}
      <Typography.Text style={{ position: 'absolute', right: 10, bottom: 6, fontSize: 11, color: '#8c8c8c' }}>{pageNumber}</Typography.Text>
    </div>
  );
}

const centerStyle: React.CSSProperties = {
  width: '100%', height: '100%', minHeight: 220, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24,
};
