import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Alert, Button, Empty, Progress, Spin, Typography } from 'antd';
import { DownloadOutlined, ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons';
import { PptxViewer, type PptxDiagnosticError } from '@file-viewer/pptx';

export interface PowerPointFilePreviewProps {
  file?: File;
  url?: string;
  filename: string;
  onDownload: () => void;
}

function errorText(error: unknown): string {
  if (error && typeof error === 'object') {
    const diagnostic = error as Partial<PptxDiagnosticError>;
    return diagnostic.message || diagnostic.detail || 'PPTX 文件解析失败';
  }
  return error instanceof Error ? error.message : String(error || 'PPTX 文件解析失败');
}

/**
 * Native PPTX renderer that deliberately keeps already-rendered slides when
 * optional post-processing fails. The generic Office adapter destroys its
 * entire presentation in that case, which turns a readable deck into a blank
 * error panel even though the worker successfully produced every slide.
 */
export default function PowerPointFilePreview({ file, url, filename, onDownload }: PowerPointFilePreviewProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<PptxViewer | null>(null);
  const hasSlidesRef = useRef(false);
  const [loading, setLoading] = useState(true);
  const [progress, setProgress] = useState(0);
  const [renderedSlides, setRenderedSlides] = useState(0);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || (!file && !url)) return;
    const controller = new AbortController();
    let disposed = false;
    hasSlidesRef.current = false;
    setLoading(true);
    setProgress(0);
    setRenderedSlides(0);
    setFatalError(null);
    setWarning(null);
    setZoom(100);

    const shadow = host.shadowRoot || host.attachShadow({ mode: 'open' });
    shadow.replaceChildren();
    const scroller = document.createElement('div');
    scroller.style.cssText = 'width:100%;height:100%;overflow:auto;background:#e8ebef;box-sizing:border-box;';
    const surface = document.createElement('div');
    surface.style.cssText = 'min-height:100%;padding:20px 18px 40px;box-sizing:border-box;';
    scroller.append(surface);
    shadow.append(scroller);

    const open = async () => {
      const buffer = file
        ? await file.arrayBuffer()
        : await fetch(url!, { signal: controller.signal }).then((response) => {
          if (!response.ok) throw new Error(`原文件读取失败（HTTP ${response.status}）`);
          return response.arrayBuffer();
        });
      if (disposed) return;
      const viewer = await PptxViewer.open(buffer, surface, {
        styleRoot: shadow,
        fitMode: 'contain',
        zoomPercent: 100,
        lazySlides: true,
        lazyMedia: true,
        listOptions: { windowed: true, initialSlides: 3, batchSize: 4, overscanViewport: 1.5 },
        onProgress: (value) => { if (!disposed) setProgress(Math.max(0, Math.min(100, Math.round(value)))); },
        onSlideRendered: (slideNumber) => {
          if (disposed) return;
          hasSlidesRef.current = true;
          setRenderedSlides((current) => Math.max(current, slideNumber));
          setLoading(false);
        },
        onRenderComplete: () => { if (!disposed) { setProgress(100); setLoading(false); } },
        onError: (reason) => {
          if (disposed) return;
          setLoading(false);
          if (hasSlidesRef.current) setWarning(errorText(reason));
          else setFatalError(errorText(reason));
        },
      });
      if (disposed) viewer.destroy();
      else viewerRef.current = viewer;
    };

    void open().catch((reason) => {
      if (!disposed && (reason as Error)?.name !== 'AbortError') {
        setLoading(false);
        if (hasSlidesRef.current) setWarning(errorText(reason));
        else setFatalError(errorText(reason));
      }
    });

    return () => {
      disposed = true;
      controller.abort();
      viewerRef.current?.destroy();
      viewerRef.current = null;
      shadow.replaceChildren();
    };
  }, [file, url]);

  const changeZoom = async (next: number) => {
    const normalized = Math.max(25, Math.min(300, next));
    setZoom(normalized);
    await viewerRef.current?.setZoom(normalized);
  };

  return (
    <div data-testid="presentation-preview" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#e8ebef' }}>
      <div style={{ minHeight: 46, flex: '0 0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 12px', background: '#fff', borderBottom: '1px solid #dfe4ea', gap: 12 }}>
        <Typography.Text ellipsis title={filename} style={{ maxWidth: 420 }}>{filename}</Typography.Text>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {loading ? `正在解析原始 PPTX${progress ? ` · ${progress}%` : ''}` : `已载入原始幻灯片${renderedSlides ? ` · 当前 ${renderedSlides} 页` : ''}`}
          </Typography.Text>
          <Button size="small" icon={<ZoomOutOutlined />} disabled={zoom <= 25} onClick={() => void changeZoom(zoom - 20)} />
          <Typography.Text style={{ width: 42, textAlign: 'center', fontSize: 12 }}>{zoom}%</Typography.Text>
          <Button size="small" icon={<ZoomInOutlined />} disabled={zoom >= 300} onClick={() => void changeZoom(zoom + 20)} />
          <Button size="small" icon={<DownloadOutlined />} onClick={onDownload}>下载</Button>
        </div>
      </div>
      {warning && renderedSlides > 0 && (
        <Alert banner showIcon type="warning" message="部分高级图表效果未完成，已保留可阅读的原始幻灯片" description={warning} closable />
      )}
      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        <div ref={hostRef} data-testid="presentation-stage" style={{ width: '100%', height: '100%' }} />
        {loading && (
          <div style={overlayStyle}><Spin /><Typography.Text type="secondary">正在读取并解析完整 PPTX…</Typography.Text><Progress percent={progress} showInfo={false} style={{ width: 240 }} /></div>
        )}
        {fatalError && !renderedSlides && (
          <div style={overlayStyle}><Empty description={`PPTX 预览失败：${fatalError}`} /><Button icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button></div>
        )}
      </div>
    </div>
  );
}

const overlayStyle: CSSProperties = {
  position: 'absolute', inset: 0, zIndex: 2, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', gap: 12, background: 'rgba(250,250,250,.94)',
};
