import { lazy, Suspense, useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import { Alert, Button, Empty, Spin, Typography } from 'antd';
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons';
import type { WorkspaceFallbackPreview, WorkspacePreviewSession } from '../../api/client';

const PdfFilePreview = lazy(() => import('./PdfFilePreview'));
const WEB_OFFICE_SDK_URL = 'https://g.alicdn.com/IMM/office-js/1.1.19/aliyun-web-office-sdk.min.js';
const WEB_OFFICE_REFRESH_MS = 25 * 60 * 1000;
const WEB_OFFICE_READABLE_TIMEOUT_MS = 15_000;

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
  onDownload: () => void;
  loadSession: () => Promise<WorkspacePreviewSession>;
  refreshSession: (accessToken: string, refreshToken: string, refreshContext: string) => Promise<WorkspacePreviewSession>;
  startFallback: () => Promise<WorkspaceFallbackPreview>;
  getFallback: () => Promise<WorkspaceFallbackPreview>;
}

export default function WorkspacePreviewSessionView({
  filename, onDownload, loadSession, refreshSession, startFallback, getFallback,
}: Props) {
  const [session, setSession] = useState<WorkspacePreviewSession | null>(null);
  const [fallback, setFallback] = useState<WorkspaceFallbackPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(() => {
    setLoading(true);
    setError(null);
    setFallback(null);
    loadSession()
      .then(setSession)
      .catch((reason) => setError((reason as Error)?.message || '预览会话创建失败'))
      .finally(() => setLoading(false));
  }, [loadSession]);

  useEffect(() => open(), [open]);

  const beginFallback = useCallback(async () => {
    setError(null);
    try {
      const value = await startFallback();
      setFallback(value);
      setSession((current) => current ? { ...current, mode: 'fallback', reason: '正在生成备用预览' } : current);
    } catch (reason) {
      setError((reason as Error)?.message || '备用预览启动失败');
    }
  }, [startFallback]);

  useEffect(() => {
    if (session?.mode !== 'fallback') return;
    if (!fallback) void beginFallback();
    if (fallback?.status === 'ready' || fallback?.status === 'failed') return;
    const timer = window.setInterval(() => {
      getFallback().then(setFallback).catch(() => undefined);
    }, 2_000);
    return () => window.clearInterval(timer);
  }, [beginFallback, fallback, getFallback, session?.mode]);

  if (loading) return <State label="正在建立安全预览会话…" />;
  if (error) return <Failure message={error} onRetry={open} onDownload={onDownload} />;
  if (!session) return <Failure message="预览会话不可用" onRetry={open} onDownload={onDownload} />;

  if (session.mode === 'weboffice' && session.weboffice_url && session.access_token && session.refresh_token) {
    if (/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)) {
      return <Failure message="移动端暂不提供完整 Office 在线预览，请下载原文件查看" onRetry={open} onDownload={onDownload} />;
    }
    return (
      <WebOfficeFrame
        session={session}
        refreshSession={refreshSession}
        onUnavailable={() => {
          if (session.mime_type === 'application/pdf' && session.url) {
            setSession({ ...session, mode: 'pdfjs', reason: 'WebOffice 超时，已切换 PDF 预览' });
          } else {
            void beginFallback();
          }
        }}
        onDownload={onDownload}
      />
    );
  }

  if (session.mode === 'pdfjs' && session.url) {
    return (
      <Suspense fallback={<State label="正在加载 PDF 查看器…" />}>
        <div style={previewColumn}>
          {session.reason && <StatusBanner text={session.reason} />}
          <PdfFilePreview url={session.url} filename={session.filename || filename} onDownload={onDownload} />
        </div>
      </Suspense>
    );
  }

  if (session.mode === 'fallback') {
    if (fallback?.status === 'ready' && fallback.url) {
      return (
        <Suspense fallback={<State label="正在打开备用预览…" />}>
          <div style={previewColumn}>
            <StatusBanner text="WebOffice 未能及时打开，当前显示备用 PDF" />
            <PdfFilePreview url={fallback.url} filename={session.filename || filename} onDownload={onDownload} />
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

  return <Failure message={session.reason || '该文件暂不支持在线预览'} onRetry={open} onDownload={onDownload} />;
}

function WebOfficeFrame({ session, refreshSession, onUnavailable, onDownload }: {
  session: WorkspacePreviewSession;
  refreshSession: Props['refreshSession'];
  onUnavailable: () => void;
  onDownload: () => void;
}) {
  const mountRef = useRef<HTMLDivElement | null>(null);
  const tokenRef = useRef(session);
  const unavailableRef = useRef(onUnavailable);
  const readableRef = useRef(false);
  const [readable, setReadable] = useState(false);
  tokenRef.current = session;
  unavailableRef.current = onUnavailable;

  useEffect(() => {
    let disposed = false;
    let unavailableTriggered = false;
    let instance: AliyunOfficeInstance | undefined;
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
    const timeout = window.setTimeout(() => {
      if (!readableRef.current) failOnce();
    }, WEB_OFFICE_READABLE_TIMEOUT_MS);

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
            refreshSession(current.access_token, current.refresh_token, current.refresh_context)
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
      window.clearTimeout(timeout);
      instance?.ApiEvent?.RemoveApiEventListener('fileOpen', markReadable);
      instance?.ApiEvent?.RemoveApiEventListener('error', failOnce);
      instance?.ApiEvent?.RemoveApiEventListener('filePasswordStatus', failOnce);
      instance?.off?.('fileOpen', markReadable);
      instance?.off?.('error', failOnce);
      instance?.off?.('filePasswordStatus', failOnce);
      instance?.destroy?.();
      if (mountRef.current) mountRef.current.replaceChildren();
    };
  }, [refreshSession, session.access_token, session.weboffice_url]);

  return (
    <div style={{ width: '100%', height: '100%', minHeight: 0, position: 'relative', background: '#f5f6f8' }}>
      {!readable && <div style={{ position: 'absolute', inset: 0, zIndex: 1 }}><State label="WebOffice 正在打开，15 秒内未就绪将自动降级…" download={onDownload} /></div>}
      <div ref={mountRef} data-testid="weboffice-preview" style={{ width: '100%', height: '100%' }} />
    </div>
  );
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
