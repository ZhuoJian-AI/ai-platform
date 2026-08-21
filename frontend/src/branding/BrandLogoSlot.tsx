import type { CSSProperties } from 'react';

/**
 * BRAND_LOGO_SLOT
 *
 * 所有等待企业品牌素材的前端 Logo 位都必须通过本组件渲染。
 * 替换 Logo 时可全局搜索 `BRAND_LOGO_SLOT` 或 `data-brand-logo-slot`，
 * 不要重新在业务页面中写死图片路径。
 */
export const BRAND_LOGO_SLOTS = {
  adminSidebar: 'admin-sidebar',
  platformLogin: 'platform-admin-login',
  organizationLogin: 'organization-admin-login',
  terminalLogin: 'terminal-user-login',
  terminalWelcome: 'terminal-welcome',
  assistantAvatar: 'assistant-avatar',
  platformFavicon: 'platform-favicon',
  terminalFavicon: 'terminal-favicon',
} as const;

export type BrandLogoSlotId = typeof BRAND_LOGO_SLOTS[keyof typeof BRAND_LOGO_SLOTS];

interface BrandLogoSlotProps {
  slot: BrandLogoSlotId;
  width: number | string;
  height: number | string;
  style?: CSSProperties;
}

/** 品牌 Logo 留白槽。当前故意不展示任何图形，仅保留原布局尺寸和 DOM 标记。 */
export default function BrandLogoSlot({ slot, width, height, style }: BrandLogoSlotProps) {
  return (
    <span
      aria-hidden="true"
      className="brand-logo-slot"
      data-brand-logo-slot={slot}
      data-brand-logo-status="awaiting-company-logo"
      style={{ display: 'block', width, height, flex: '0 0 auto', ...style }}
    />
  );
}

const BLANK_FAVICON = 'data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%2232%22 height=%2232%22 viewBox=%220 0 32 32%22%3E%3C/svg%3E';

/** BRAND_LOGO_SLOT: 浏览器标签图标留白，并在离开当前路由时恢复上一个位点。 */
export function markBlankFavicon(slot: BrandLogoSlotId): () => void {
  let link = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  const created = !link;
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    document.head.appendChild(link);
  }

  const previous = {
    href: link.getAttribute('href'),
    type: link.getAttribute('type'),
    slot: link.dataset.brandLogoSlot,
    status: link.dataset.brandLogoStatus,
  };

  link.type = 'image/svg+xml';
  link.href = BLANK_FAVICON;
  link.dataset.brandLogoSlot = slot;
  link.dataset.brandLogoStatus = 'awaiting-company-logo';

  return () => {
    if (created) {
      link?.remove();
      return;
    }
    if (previous.href === null) link?.removeAttribute('href');
    else link?.setAttribute('href', previous.href);
    if (previous.type === null) link?.removeAttribute('type');
    else link?.setAttribute('type', previous.type);
    if (previous.slot === undefined) delete link?.dataset.brandLogoSlot;
    else if (link) link.dataset.brandLogoSlot = previous.slot;
    if (previous.status === undefined) delete link?.dataset.brandLogoStatus;
    else if (link) link.dataset.brandLogoStatus = previous.status;
  };
}
