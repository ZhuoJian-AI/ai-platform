# 企业品牌 Logo 待替换位

当前运行界面的旧品牌图片已经全部断开引用，页面只保留原尺寸留白。以后放入企业 Logo 时，请全局搜索：

- `BRAND_LOGO_SLOT`：源码标记。
- `data-brand-logo-slot`：浏览器 DOM 标记。
- `awaiting-company-logo`：尚未配置企业 Logo 的状态标记。

## 位点清单

| 标记 | 页面/用途 | 当前预留尺寸 |
| --- | --- | --- |
| `admin-sidebar` | 最高管理员、平台管理员、组织管理员共用侧栏 | 高 26px，最大宽 188px |
| `platform-admin-login` | 最高管理员/平台管理员登录 | 200×56px |
| `organization-admin-login` | 企业组织管理员登录 | 200×56px |
| `terminal-user-login` | 企业普通用户登录 | 200×56px |
| `terminal-welcome` | 用户端新任务欢迎页 | 72×72px |
| `assistant-avatar` | 用户端 AI 回复头像 | 28×28px |
| `platform-favicon` | 管理端浏览器标签图标 | 32×32px |
| `terminal-favicon` | 用户端浏览器标签图标 | 32×32px |

## 明确不属于 Logo 的图片

- `public/contact-qr.png`：联系二维码。
- 用户上传、AI 生成、文档预览中的图片：业务内容。

旧文件 `public/logo.png`、`public/admin-icon.png`、`public/terminal-icon.png` 暂时保留用于追溯，但运行界面不再引用。后续确认新企业 Logo 后，可在 `BrandLogoSlot.tsx` 集中接入，不应把图片路径重新散落到业务页面。
