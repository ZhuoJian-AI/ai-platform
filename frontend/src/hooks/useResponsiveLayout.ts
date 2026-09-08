import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';

export const MOBILE_MAX_WIDTH = 768;
export const COMPACT_MAX_WIDTH = 1199;

function readViewport(): { width: number; height: number } {
  if (typeof window === 'undefined') return { width: 1440, height: 900 };
  return { width: window.innerWidth, height: window.innerHeight };
}

/**
 * 只用于决定抽屉、焦点和 inert 等交互状态。
 * 连续缩放与视觉布局仍由 CSS media/container queries 负责，避免在组件里复制布局逻辑。
 */
export function useResponsiveLayout() {
  const [viewport, setViewport] = useState(readViewport);

  useEffect(() => {
    let frame = 0;
    const syncVisualViewport = () => {
      const height = window.visualViewport?.height ?? window.innerHeight;
      document.documentElement.style.setProperty('--zj-visual-viewport-height', `${Math.round(height)}px`);
    };
    const update = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        setViewport(readViewport());
        syncVisualViewport();
      });
    };
    syncVisualViewport();
    window.addEventListener('resize', update, { passive: true });
    window.addEventListener('orientationchange', update, { passive: true });
    window.visualViewport?.addEventListener('resize', syncVisualViewport, { passive: true });
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
      window.removeEventListener('orientationchange', update);
      window.visualViewport?.removeEventListener('resize', syncVisualViewport);
    };
  }, []);

  const isLandscapeHandset = viewport.width <= 900 && viewport.height <= 500;
  return {
    viewportWidth: viewport.width,
    viewportHeight: viewport.height,
    isMobile: viewport.width <= MOBILE_MAX_WIDTH || isLandscapeHandset,
    isCompact: viewport.width <= COMPACT_MAX_WIDTH,
  };
}

/** 手机返回键优先关闭浮层，不让用户意外离开当前业务页面。 */
export function useMobileBackDismiss(
  open: boolean,
  enabled: boolean,
  setOpen: Dispatch<SetStateAction<boolean>>,
  layerName: string,
) {
  const markerRef = useRef<string | null>(null);

  useEffect(() => {
    if (!open || !enabled) {
      const marker = markerRef.current;
      if (marker && window.history.state?.__zhuojianResponsiveLayer === marker) {
        const { __zhuojianResponsiveLayer: _discarded, ...rest } = window.history.state;
        window.history.replaceState(rest, document.title);
      }
      markerRef.current = null;
      return;
    }
    if (markerRef.current) return;
    const marker = `${layerName}:${crypto.randomUUID()}`;
    markerRef.current = marker;
    const current = window.history.state;
    const state = current && typeof current === 'object' ? current : {};
    window.history.pushState({ ...state, __zhuojianResponsiveLayer: marker }, document.title);
    const onPopState = () => {
      if (markerRef.current !== marker) return;
      markerRef.current = null;
      setOpen(false);
    };
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, [enabled, layerName, open, setOpen]);

  return useCallback(() => {
    const marker = markerRef.current;
    setOpen(false);
    if (marker && window.history.state?.__zhuojianResponsiveLayer === marker) {
      markerRef.current = null;
      window.history.back();
    }
  }, [setOpen]);
}
