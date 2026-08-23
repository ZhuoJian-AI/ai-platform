# 企业品牌 Logo 位点

全部品牌位统一使用 `public/brand/aisee-logo.svg`。后续调整企业 Logo 时，请全局搜索：

- `BRAND_LOGO_SLOT`：源码标记。
- `data-brand-logo-slot`：浏览器 DOM 标记。
- `configured`：已配置企业 Logo 的状态标记。

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

旧文件 `public/logo.png`、`public/admin-icon.png`、`public/terminal-icon.png` 暂时保留用于追溯，但运行界面不再引用。品牌资源只应在 `BrandLogoSlot.tsx` 集中接入，不应把图片路径重新散落到业务页面。
