import { useEffect } from 'react';

export const BRAND_NAME = '灼见';

export const BRAND_TITLES = {
  platform: '灼见-平台级管理员界面',
  organization: '灼见-企业级管理员界面',
  terminal: '灼见-用户界面',
} as const;

export type BrandTitle = typeof BRAND_TITLES[keyof typeof BRAND_TITLES];

/** Route shells own the browser title so all three portals remain distinguishable. */
export function useBrandTitle(title: BrandTitle): void {
  useEffect(() => {
    document.title = title;
  }, [title]);
}
