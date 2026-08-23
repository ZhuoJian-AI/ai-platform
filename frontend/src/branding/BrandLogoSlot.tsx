import type { CSSProperties } from 'react';

/**
 * BRAND_LOGO_SLOT
 *
 * 所有企业品牌 Logo 位都必须通过本组件渲染。
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

export const BRAND_LOGO_URL = '/brand/aisee-logo.svg';

interface BrandLogoSlotProps {
  slot: BrandLogoSlotId;
  width: number | string;
  height: number | string;
  style?: CSSProperties;
}

/** 统一品牌 Logo 槽，保留位点标记并渲染同一份灼见 AiSEE SVG。 */
export default function BrandLogoSlot({ slot, width, height, style }: BrandLogoSlotProps) {
  return (
    <span
      className="brand-logo-slot"
      data-brand-logo-slot={slot}
      data-brand-logo-status="configured"
      style={{ display: 'block', width, height, flex: '0 0 auto', ...style }}
    >
      <img
        src={BRAND_LOGO_URL}
        alt="灼见 AiSEE"
        draggable={false}
        style={{ display: 'block', width: '100%', height: '100%', objectFit: 'contain' }}
      />
    </span>
  );
}

/** BRAND_LOGO_SLOT: 应用统一浏览器标签图标，并在离开当前路由时恢复上一个位点。 */
export function applyBrandFavicon(slot: BrandLogoSlotId): () => void {
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
  link.href = BRAND_LOGO_URL;
  link.dataset.brandLogoSlot = slot;
  link.dataset.brandLogoStatus = 'configured';

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
