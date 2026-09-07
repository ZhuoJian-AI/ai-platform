# 业务助手意图校验兼容修复发布

## 发布范围

- 负责人：Codex
- 任务：`PLAT-BUSINESS-INTENT-DEEPSEEK-COMPAT-004`
- 产品源提交：`33697de0089eff84f04ce472afbee8d3e2670db7`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 只更新共用 SaaS 后端镜像；前端 Nginx 镜像、域名、数据库和子系统均不变。

## 不可变镜像

- 后端旧 digest：`sha256:ba47ba3891e57f83e8811a8a06dcccbc17d68c68af0602562038a1acbf20589e`
- 后端新 digest：`sha256:13895c73dad09dce8ed60ac93377f1ce26bb497d36046c7a0390add05ad16990`
- 新镜像架构：`linux/amd64`
- OCI revision：`33697de0089eff84f04ce472afbee8d3e2670db7`
- 源码归档 SHA-256：`74af5411b941feb334c186d9235dd3726f267259464280c68372ebde19d47e54`

## 已完成验证

- 源分支 37 项意图编排、DeepSeek 兼容和 DSH Bridge 测试通过；Ruff 通过。
- 镜像内 `import app.main` 通过，同一组 37 项测试通过。
- Registry 返回的新 digest、镜像架构和 OCI revision 已核对。
- 本次没有数据库迁移，不执行数据库备份。

## 发布后验收

- 核对五个共用后端服务运行新 digest 且全部健康。
- 使用张三真实员工账号验证页面说明零 Action、实时查询、Excel Artifact、对话隔离和 URL 恢复。
- 确认普通查询与导出不触发 iframe 整页刷新。

## 回退

- 异常时只恢复旧后端 digest，不回滚数据库。

## 规则依据

- `ZhuoJian-AI/zhuojian-server-deploy`：`c948cd2`
