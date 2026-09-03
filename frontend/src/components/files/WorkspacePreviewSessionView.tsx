import { lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Alert, Button, Empty, Spin, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import type {
  WorkspaceFallbackPreview, WorkspacePreviewPreferredMode, WorkspacePreviewSession,
  WorkspaceSpreadsheetPage, WorkspaceSpreadsheetPreview,
} from '../../api/client';

const PdfFilePreview = lazy(() => import('./PdfFilePreview'));
const OfficeFilePreview = lazy(() => import('./OfficeFilePreview'));
const SpreadsheetPagedPreview = lazy(() => import('./SpreadsheetPagedPreview'));
const WEB_OFFICE_SDK_URL = 'https://g.alicdn.com/IMM/office-js/1.1.19/aliyun-web-office-sdk.min.js';
const WEB_OFFICE_REFRESH_MS = 25 * 60 * 1000;
const WEB_OFFICE_SLOW_MS = 15_000;
const WEB_OFFICE_FALLBACK_MS = 30_000;

interface AliyunOfficeInstance {
  setToken: (value: { token: string; timeout: number }) => void;
  ready?: () => Promise<void>;
  ApiEvent?: {
    AddApiEventListener: (name: string, listener: (data?: { success?: boolean }) => void) => void;
    RemoveApiEventListener: (name: string, listener: (data?: { success?: boolean }) => void) => void;
  };
  on?: (name: string, listener: (data?: { success?: boolean }) => void) => void;
  off?: (name: string, listener: (data?: { success?: boolean }) => void) => void;
  destroy?: () => void;
}

declare global {
  interface Window {
    aliyun?: {
      config: (options: {
        mount: HTMLElement;
        url: string;
        refreshToken: () => Promise<{ token: string; timeout: number }>;
      }) => AliyunOfficeInstance;
    };
  }
}

let sdkPromise: Promise<void> | null = null;
function loadWebOfficeSdk(): Promise<void> {
  if (window.aliyun) return Promise.resolve();
  if (sdkPromise) return sdkPromise;
  const pending = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${WEB_OFFICE_SDK_URL}"]`);
    const script = existing || document.createElement('script');
    const onLoad = () => window.aliyun ? resolve() : reject(new Error('WebOffice SDK 未初始化'));
    const onError = () => reject(new Error('WebOffice SDK 加载失败'));
    script.addEventListener('load', onLoad, { once: true });
    script.addEventListener('error', onError, { once: true });
    if (!existing) {
      script.src = WEB_OFFICE_SDK_URL;
      script.async = true;
      script.referrerPolicy = 'no-referrer';
      document.head.appendChild(script);
    }
  }).catch((error) => {
    sdkPromise = null;
    throw error;
  });
  sdkPromise = pending;
  return pending;
}

interface Props {
  filename: string;
  previewKey: string;
  onDownload: () => void;
  loadSession: (clientOpenId: string, preferredMode?: WorkspacePreviewPreferredMode) => Promise<WorkspacePreviewSession>;
  refreshSession: (accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  startFallback: () => Promise<WorkspaceFallbackPreview>;
  getFallback: () => Promise<WorkspaceFallbackPreview>;
  startSpreadsheet?: () => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheet?: () => Promise<WorkspaceSpreadsheetPreview>;
  getSpreadsheetPage?: (sheet: string, page: number) => Promise<WorkspaceSpreadsheetPage>;
}

const openIds = new Map<string, { id: string; expiresAt: number }>();
const sessionFlights = new Map<string, Promise<WorkspacePreviewSession>>();

function clientOpenId(previewKey: string): string {
  const cached = openIds.get(previewKey);
  if (cached && cached.expiresAt > Date.now()) return cached.id;
  const id = crypto.randomUUID().replace(/-/g, '');
  openIds.set(previewKey, { id, expiresAt: Date.now() + 60_000 });
  return id;
}

function loadSingleFlight(
  key: string, loader: () => Promise<WorkspacePreviewSession>,
): Promise<WorkspacePreviewSession> {
  const existing = sessionFlights.get(key);
  if (existing) return existing;
  const pending = loader().finally(() => sessionFlights.delete(key));
  sessionFlights.set(key, pending);
  return pending;
}

export default function WorkspacePreviewSessionView({
  filename, previewKey, onDownload, loadSession, refreshSession, startFallback, getFallback,
  startSpreadsheet, getSpreadsheet, getSpreadsheetPage,
}: Props) {
  const [session, setSession] = useState<WorkspacePreviewSession | null>(null);
  const [fallback, setFallback] = useState<WorkspaceFallbackPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const loadSessionRef = useRef(loadSession);
  const startFallbackRef = useRef(startFallback);
  const getFallbackRef = useRef(getFallback);
  const openIdRef = useRef(clientOpenId(previewKey));
  const isPresentation = ['ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'ppsm', 'pot', 'potx', 'potm', 'odp'].includes(extensionOf(filename));
  loadSessionRef.current = loadSession;
  startFallbackRef.current = startFallback;
  getFallbackRef.current = getFallback;

  const open = useCallback((preferredMode: WorkspacePreviewPreferredMode = 'default') => {
    setLoading(true);
    setError(null);
    setFallback(null);
    const selectMode = async () => {
      if (preferredMode === 'default' && isPresentation) {
        const cachedFallback = await getFallbackRef.current().catch(() => null);
        if (cachedFallback?.status === 'ready') {
          setFallback(cachedFallback);
          return 'fast_layout' as const;
        }
      }
      return preferredMode;
    };
    selectMode().then((selectedMode) => loadSingleFlight(
      `${previewKey}:${openIdRef.current}:${selectedMode}`,
      () => loadSessionRef.current(openIdRef.current, selectedMode),
    ))
      .then(setSession)
      .catch((reason) => setError((reason as Error)?.message || '预览会话创建失败'))
      .finally(() => setLoading(false));
  }, [isPresentation, previewKey]);

  useEffect(() => open(), [filename, open]);

  const beginFallback = useCallback(async (switchNow = true) => {
    setError(null);
    try {
      const value = await startFallbackRef.current();
      setFallback(value);
      if (switchNow) setSession((current) => current ? { ...current, mode: 'fallback', reason: '正在生成备用预览' } : current);
    } catch (reason) {
      setError((reason as Error)?.message || '备用预览启动失败');
    }
  }, []);

  useEffect(() => {
    if (session?.mode !== 'fallback' && session?.mode !== 'weboffice') return;
    if (session.mode === 'fallback' && !fallback) void beginFallback();
    if (!fallback) return;
    if (fallback?.status === 'ready' || fallback?.status === 'failed') return;
    const timer = window.setInterval(() => {
      getFallbackRef.current().then(setFallback).catch(() => undefined);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [beginFallback, fallback, session?.mode]);

  useEffect(() => {
    if (session?.mode !== 'weboffice' || fallback) return;
    getFallbackRef.current().then((value) => {
      if (value.status !== 'missing') setFallback(value);
    }).catch(() => undefined);
  }, [fallback, session?.mode]);

  if (loading) return <State label="正在建立安全预览会话…" />;
  if (error) return <Failure message={error} onRetry={() => open()} onDownload={onDownload} />;
  if (!session) return <Failure message="预览会话不可用" onRetry={() => open()} onDownload={onDownload} />;

  if (session.mode === 'weboffice' && session.weboffice_url && session.access_token && session.refresh_token) {
    if (/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)) {
      return <Failure message="移动端暂不提供完整 Office 在线预览，请下载原文件查看" onRetry={open} onDownload={onDownload} />;
    }
    return (
      <WebOfficeFrame
        session={session}
        refreshSession={refreshSession}
        onSlow={() => void beginFallback(false)}
        onUseFallback={() => void beginFallback(true)}
        onUnavailable={() => void beginFallback(true)}
        fallbackReady={fallback?.status === 'ready'}
        onDownload={onDownload}
      />
    );
  }

  if (session.mode === 'pdfjs' && session.url) {
    return (
      <Suspense fallback={<State label="正在加载 PDF 查看器…" />}>
        <div style={previewColumn}>
          {session.reason && <StatusBanner text={session.reason} />}
        <PdfFilePreview url={session.url} fallbackUrl={session.fallback_url || undefined} filename={session.filename || filename} onDownload={onDownload} strictRange={session.strict_range} />
      </div>
      </Suspense>
    );
  }

  if (session.mode === 'browser_office' && session.url) {
    const extension = extensionOf(session.filename || filename);
    return (
      <Suspense fallback={<State label="正在加载本地 Office 查看器…" />}>
        <OfficeFilePreview
          url={session.url}
          fallbackUrl={session.fallback_url || undefined}
          filename={session.filename || filename}
          extension={extension}
          size={session.size}
          onDownload={onDownload}
        />
      </Suspense>
    );
  }

  if (session.mode === 'text' && session.url) {
    return <TextPreview url={session.url} fallbackUrl={session.fallback_url} onDownload={onDownload} />;
  }

  if (session.mode === 'spreadsheet_preview') {
    if (!startSpreadsheet || !getSpreadsheet || !getSpreadsheetPage) {
      return <Failure message="分页表格预览接口不可用" onRetry={() => open()} onDownload={onDownload} />;
    }
    return (
      <Suspense fallback={<State label="正在加载分页表格查看器…" />}>
        <SpreadsheetPagedPreview
          filename={session.filename || filename}
          onDownload={onDownload}
          startPreview={startSpreadsheet}
          getPreview={getSpreadsheet}
          getPage={getSpreadsheetPage}
        />
      </Suspense>
    );
  }

  if (session.mode === 'fallback') {
    if (fallback?.status === 'ready' && fallback.url) {
      return (
        <Suspense fallback={<State label="正在打开备用预览…" />}>
          <div style={previewColumn}>
            <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'center', gap: 8, background: '#fffbe6' }}>
              <div style={{ flex: 1 }}><StatusBanner text={isPresentation ? '当前显示免费快速版式预览；动画、视频和播放模式请使用交互预览。' : '当前显示后台生成并按文件版本复用的版式预览。'} /></div>
              {isPresentation && <Button size="small" onClick={() => open('interactive_ppt')}>打开 WebOffice 交互预览</Button>}
            </div>
            <PdfFilePreview url={fallback.url} fallbackUrl={fallback.fallback_url || undefined} filename={session.filename || filename} onDownload={onDownload} />
          </div>
        </Suspense>
      );
    }
    if (fallback?.status === 'failed') {
      return <Failure message={fallback.error || '备用预览生成失败'} onRetry={beginFallback} onDownload={onDownload} />;
    }
    return <State label={`正在生成备用预览${fallback ? `（第 ${fallback.attempt_count}/3 次）` : ''}…`} download={onDownload} />;
  }

  if ((session.mode === 'native') && session.url) {
    if (session.mime_type.startsWith('image/')) return <div style={center}><img src={session.url} alt={filename} style={{ maxWidth: '100%', maxHeight: '100%', objectFit: 'contain' }} /></div>;
    if (session.mime_type.startsWith('video/')) return <div style={center}><video controls src={session.url} style={{ maxWidth: '100%', maxHeight: '100%' }} /></div>;
    if (session.mime_type.startsWith('audio/')) return <div style={center}><audio controls src={session.url} style={{ width: 'min(560px, 90%)' }} /></div>;
  }

  return <Failure message={session.reason || '该文件暂不支持在线预览'} onRetry={() => open()} onDownload={onDownload} />;
}

function WebOfficeFrame({ session, refreshSession, onSlow, onUseFallback, onUnavailable, fallbackReady, onDownload }: {
  session: WorkspacePreviewSession;
  refreshSession: Props['refreshSession'];
  onSlow: () => void;
  onUseFallback: () => void;
  onUnavailable: () => void;
  fallbackReady: boolean;
  onDownload: () => void;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const tokenRef = useRef(session);
  const unavailableRef = useRef(onUnavailable);
  const slowRef = useRef(onSlow);
  const refreshSessionRef = useRef(refreshSession);
  const readableRef = useRef(false);
  const [readable, setReadable] = useState(false);
  const [slow, setSlow] = useState(false);
  tokenRef.current = session;
  unavailableRef.current = onUnavailable;
  slowRef.current = onSlow;
  refreshSessionRef.current = refreshSession;

  useEffect(() => {
    let disposed = false;
    let unavailableTriggered = false;
    let instance: AliyunOfficeInstance | undefined;
    readableRef.current = false;
    setReadable(false);
    setSlow(false);
    const failOnce = () => {
      if (disposed || unavailableTriggered) return;
      unavailableTriggered = true;
      unavailableRef.current();
    };
    const markReadable = (data?: { success?: boolean }) => {
      if (data?.success === false) {
        failOnce();
        return;
      }
      if (!disposed && !unavailableTriggered) {
        readableRef.current = true;
        setReadable(true);
      }
    };
    const slowTimer = window.setTimeout(() => {
      if (!readableRef.current && !disposed) {
        setSlow(true);
        slowRef.current();
      }
    }, WEB_OFFICE_SLOW_MS);
    const fallbackTimer = window.setTimeout(() => {
      if (!readableRef.current) failOnce();
    }, WEB_OFFICE_FALLBACK_MS);

    const init = async () => {
      try {
        await loadWebOfficeSdk();
        if (disposed || !mountRef.current || !window.aliyun || !session.weboffice_url || !session.access_token) return;
        instance = window.aliyun.config({
          mount: mountRef.current,
          url: session.weboffice_url,
          refreshToken: () => new Promise((resolve, reject) => {
            const current = tokenRef.current;
            if (!current.access_token || !current.refresh_token || !current.refresh_context) {
              reject(new Error('WebOffice 刷新凭证缺失'));
              return;
            }
            refreshSessionRef.current(current.access_token, current.refresh_token, current.refresh_context)
              .then((next) => {
                tokenRef.current = { ...current, ...next };
                resolve({ token: next.access_token || '', timeout: WEB_OFFICE_REFRESH_MS });
              })
              .catch((reason) => {
                failOnce();
                reject(reason);
              });
          }),
        });
        // Alibaba's fileOpen event means the document itself is readable. An
        // iframe load only means the WebOffice shell loaded and can still leave
        // the user looking at a blank document indefinitely.
        if (instance.ApiEvent) {
          instance.ApiEvent.AddApiEventListener('fileOpen', markReadable);
          instance.ApiEvent.AddApiEventListener('error', failOnce);
          instance.ApiEvent.AddApiEventListener('filePasswordStatus', failOnce);
        } else {
          instance.on?.('fileOpen', markReadable);
          instance.on?.('error', failOnce);
          instance.on?.('filePasswordStatus', failOnce);
        }
        instance.setToken({ token: session.access_token, timeout: WEB_OFFICE_REFRESH_MS });
        void instance.ready?.().catch(failOnce);
      } catch {
        failOnce();
      }
    };
    void init();
    return () => {
      disposed = true;
      window.clearTimeout(slowTimer);
      window.clearTimeout(fallbackTimer);
      instance?.ApiEvent?.RemoveApiEventListener('fileOpen', markReadable);
      instance?.ApiEvent?.RemoveApiEventListener('error', failOnce);
      instance?.ApiEvent?.RemoveApiEventListener('filePasswordStatus', failOnce);
      instance?.off?.('fileOpen', markReadable);
      instance?.off?.('error', failOnce);
      instance?.off?.('filePasswordStatus', failOnce);
      instance?.destroy?.();
      if (mountRef.current) mountRef.current.replaceChildren();
    };
  }, [session.access_token, session.weboffice_url]);

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 0, position: 'relative', background: '#f5f6f8' }}>
      {!readable && !slow && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 1 }}>
          <div style={center}>
            <Spin />
            <Typography.Text type="secondary">WebOffice 正在打开；需要动画或播放模式请继续等待。</Typography.Text>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button icon={<ReloadOutlined />} onClick={onUseFallback}>{fallbackReady ? '免费快速版式预览' : '生成免费版式预览'}</Button>
              <Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
            </div>
          </div>
        </div>
      )}
      {!readable && slow && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 1 }}>
          <div style={center}>
            <Spin />
            <Typography.Text type="secondary">WebOffice 仍在加载，后台已准备免费版式预览；最迟 30 秒自动切换。</Typography.Text>
            <div style={{ display: 'flex', gap: 8 }}>
              <Button icon={<ReloadOutlined />} onClick={onUseFallback}>{fallbackReady ? '打开快速版式预览' : '查看备用预览进度'}</Button>
              <Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
            </div>
          </div>
        </div>
      )}
      <div ref={mountRef} data-testid="weboffice-preview" style={{ width: '100%', height: '100%' }} />
    </div>
  );
}

function TextPreview({ url, fallbackUrl, onDownload }: { url: string; fallbackUrl?: string | null; onDownload: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        let response = await fetch(url, { signal: controller.signal });
        if (!response.ok && fallbackUrl) response = await fetch(fallbackUrl, { signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        setText(await response.text());
      } catch (reason) {
        if ((reason as Error).name !== 'AbortError') setError((reason as Error)?.message || '文本读取失败');
      }
    };
    void load();
    return () => controller.abort();
  }, [fallbackUrl, retry, url]);
  if (error) return <Failure message={`文本预览失败：${error}`} onRetry={() => { setError(null); setText(null); setRetry((value) => value + 1); }} onDownload={onDownload} />;
  if (text === null) return <State label="正在读取文本…" download={onDownload} />;
  return <div style={{ height: '100%', overflow: 'auto', padding: '16px 20px', background: '#fafafa' }}><pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: 'Consolas, monospace' }}>{text}</pre></div>;
}

function extensionOf(filename: string): string {
  const index = filename.lastIndexOf('.');
  return index >= 0 ? filename.slice(index + 1).toLowerCase() : '';
}

function StatusBanner({ text }: { text: string }) {
  return <Alert banner type="warning" showIcon message={text} style={{ flex: '0 0 auto' }} />;
}

function State({ label, download }: { label: string; download?: () => void }) {
  return <div style={center}><Spin /><Typography.Text type="secondary">{label}</Typography.Text>{download && <Button icon={<DownloadOutlined />} onClick={download}>下载原文件</Button>}</div>;
}

function Failure({ message, onRetry, onDownload }: { message: string; onRetry: () => void; onDownload: () => void }) {
  return (
    <div style={center}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={message} />
      <div style={{ display: 'flex', gap: 8 }}>
        <Button icon={<ReloadOutlined />} onClick={onRetry}>重试预览</Button>
        <Button type="primary" icon={<DownloadOutlined />} onClick={onDownload}>下载原文件</Button>
      </div>
    </div>
  );
}

const center: CSSProperties = {
  width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column',
  alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24, background: '#fafafa',
};

const previewColumn: CSSProperties = {
  width: '100%', height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column',
};
