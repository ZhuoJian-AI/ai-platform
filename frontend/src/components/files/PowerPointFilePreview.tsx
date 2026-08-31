import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Alert, Button, Empty, Progress, Spin, Typography } from 'antd';
import {
  CompressOutlined,
  DownloadOutlined,
  FullscreenExitOutlined,
  FullscreenOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from '@ant-design/icons';
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
  const rootRef = useRef<HTMLDivElement | null>(null);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<PptxViewer | null>(null);
  const hasSlidesRef = useRef(false);
  const [loading, setLoading] = useState(true);
  const [visualReady, setVisualReady] = useState(false);
  const [progress, setProgress] = useState(0);
  const [renderedSlides, setRenderedSlides] = useState(0);
  const [fatalError, setFatalError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [zoom, setZoom] = useState(100);
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    const syncFullscreen = () => setFullscreen(document.fullscreenElement === rootRef.current);
    document.addEventListener('fullscreenchange', syncFullscreen);
    return () => document.removeEventListener('fullscreenchange', syncFullscreen);
  }, []);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || (!file && !url)) return;
    const controller = new AbortController();
    let disposed = false;
    hasSlidesRef.current = false;
    setLoading(true);
    setVisualReady(false);
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
        // Most PPTX files contain PowerPoint's own first-page thumbnail. Keep it
        // visible while the worker parses the remaining slides instead of
        // covering it with a full-panel loading mask.
        onThumbnail: () => { if (!disposed) setVisualReady(true); },
        onSlideRendered: (slideNumber) => {
          if (disposed) return;
          hasSlidesRef.current = true;
          setVisualReady(true);
          setRenderedSlides((current) => Math.max(current, slideNumber));
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

  const toggleFullscreen = async () => {
    if (document.fullscreenElement === rootRef.current) {
      await document.exitFullscreen();
      return;
    }
    await rootRef.current?.requestFullscreen();
  };

  return (
    <div ref={rootRef} data-testid="presentation-preview" style={{ width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#e8ebef' }}>
      <div style={{ flex: '0 0 auto', display: 'flex', flexDirection: 'column', padding: '7px 12px 0', background: '#fff', borderBottom: '1px solid #dfe4ea', gap: 6 }}>
        <div style={{ minHeight: 32, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <Typography.Text ellipsis title={filename} style={{ minWidth: 120, maxWidth: 360, flex: '1 1 auto', fontWeight: 500 }}>{filename}</Typography.Text>
          <div aria-label="PPT 预览工具栏" style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', flexWrap: 'wrap', gap: 6, flex: '0 0 auto' }}>
            <Button size="small" icon={<ZoomOutOutlined />} disabled={zoom <= 25} onClick={() => void changeZoom(zoom - 20)}>缩小</Button>
            <Button size="small" style={{ minWidth: 58, cursor: 'default' }}>{zoom}%</Button>
            <Button size="small" icon={<ZoomInOutlined />} disabled={zoom >= 300} onClick={() => void changeZoom(zoom + 20)}>放大</Button>
            <Button size="small" icon={<CompressOutlined />} disabled={zoom === 100} onClick={() => void changeZoom(100)}>适应窗口</Button>
            <Button size="small" icon={fullscreen ? <FullscreenExitOutlined /> : <FullscreenOutlined />} onClick={() => void toggleFullscreen()}>{fullscreen ? '退出全屏' : '全屏'}</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={onDownload}>下载</Button>
          </div>
        </div>
        <div style={{ minHeight: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {loading
              ? visualReady ? `首屏已显示，正在后台解析其余页面${progress ? ` · ${progress}%` : ''}` : `正在读取原始 PPTX${progress ? ` · ${progress}%` : ''}`
              : `已载入原始幻灯片${renderedSlides ? ` · 当前 ${renderedSlides} 页` : ''}`}
          </Typography.Text>
          {loading && <Progress percent={progress} showInfo={false} size="small" style={{ width: 120, margin: 0 }} />}
        </div>
      </div>
      {warning && renderedSlides > 0 && (
        <Alert banner showIcon type="warning" message="部分高级图表效果未完成，已保留可阅读的原始幻灯片" description={warning} closable />
      )}
      <div style={{ position: 'relative', flex: 1, minHeight: 0 }}>
        <div ref={hostRef} data-testid="presentation-stage" style={{ width: '100%', height: '100%' }} />
        {loading && !visualReady && (
          <div style={overlayStyle}><Spin /><Typography.Text type="secondary">正在读取 PPTX，首张幻灯片生成后即可查看…</Typography.Text><Progress percent={progress} showInfo={false} style={{ width: 240 }} /></div>
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
