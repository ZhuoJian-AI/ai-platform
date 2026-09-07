# 业务查询编译与历史页面上下文发布

## 发布范围

- 负责人：Codex
- 任务：`PLAT-BUSINESS-ORCHESTRATION-RELEASE-003`、`PLAT-BUSINESS-INTENT-DEEPSEEK-COMPAT-004`
- 产品源提交：`bac1e5796f1fc0d5e8deea193870455f09edabaa`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 只更新共用 SaaS 后端镜像；前端 Nginx 镜像、域名、数据库、Skill 和子系统均不变。

## 不可变镜像

- 后端旧 digest：`sha256:13895c73dad09dce8ed60ac93377f1ce26bb497d36046c7a0390add05ad16990`
- 后端新 digest：`sha256:0805b83d96d491daa16411c2dac41fc6184fe3c34e59c3c747b91f2492c243d8`
- 新镜像架构：`linux/amd64`
- OCI revision：`bac1e5796f1fc0d5e8deea193870455f09edabaa`
- 源码归档 SHA-256：`07979ef3496607a7b43d0bfe0809bd205f6994dc096decb6ad58ebc10052d8a1`

## 已完成验证

- 源分支 49 项业务编排、页面上下文、DeepSeek 兼容和 DSH Bridge 测试通过；Ruff 通过。
- 镜像内 `import app.main` 通过，同一组 49 项测试通过。
- Registry 返回的新 digest、镜像架构和 OCI revision 已核对。
- 本次没有数据库迁移，不执行数据库备份。

## 发布后验收

- 核对五个共用后端服务运行新 digest且全部健康。
- 使用张三真实员工账号验证风险订单查询只调用一次 Action。
- 验证新旧业务对话均显示规范页面名，切换、刷新及 URL 恢复正确。
- 记录 iframe DOM 标记与 `src`，确认查询完成后没有重建或导航。

## 回退

- 异常时只恢复旧后端 digest，不回滚数据库。

## 规则依据

- `ZhuoJian-AI/zhuojian-server-deploy`：`c948cd2`
