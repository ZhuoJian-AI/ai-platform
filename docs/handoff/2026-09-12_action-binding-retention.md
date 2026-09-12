# 已结束请求的加密绑定摘要

在现有 params_encrypted 内保存有版本标识的仅绑定结构：参数摘要、页面和版本，不保留完整业务参数。成功、明确失败、取消、过期及重复请求被拒绝时退役完整参数；结果未知仍保留原加密参数供核实。重复提交同一 requestId 仍实时鉴权，并按原参数摘要校验；不同参数不能借用旧回执。仅摘要记录禁止重新执行，也不参与按完整参数匹配未知操作，避免空参数误匹配。

无新表、迁移、服务或模型 Schema。旧镜像对已结束仅摘要记录最多拒绝重放，不会把该记录重新执行；不将结果记录改回 pending。旧记录已清空参数时不伪造绑定，本批不实现跨轮新工具 ID 的逻辑去重。

验证：119 项聚焦测试通过（test_action_unknown_outcome.py、test_action_reconciliation.py、test_enterprise_action_hardening.py），Ruff 通过。覆盖成功与超时执行、摘要清理、同参数复用、改参数拒绝、禁止仅摘要再执行，沿用未知写入与人工核实回归。未做新的真实员工业务写入实测。

状态：2026-09-13 已部署。源码 PR #157，source `695ca9cc756c8fa119ca5db8ebb9a5b9289d9b2d`；backend/共享 worker digest `sha256:d402f74bb67e84909dc21d0c60d61183238138d6895cb783b9d524ce7219ab2c`；manifest PR #158、`c1bfef1eb92410754c605881279e908a7879c5d4`；Coolify `voicefix219338eaa1b1bfbf` finished，无待发布配置。

运行 backend digest 与 OCI source 匹配；前端仍为 source 28dcfbd、digest `sha256:23e69fe1c4e1e1fab64050502bf77630e6b7f6b98a0fe568b683e6759cfbbf9d`。Compose PASS（registry-image、无源码构建或仓库 bind mount、数据库端口未公开）；9 服务 healthy，必填运行值和共享令牌检查通过。公网 /health 200，root 现有真实浏览器会话刷新与 auth/me 200。未新增员工业务写入验收。

无迁移、不需备份；未改 OSS，不重复存储验收。临时构建文件已清理，旧镜像、业务数据和工作空间文件保留。仓库：https://github.com/ZhuoJian-AI/ai-platform；服务：https://ai-platform.staging.zhuojianai.com；Coolify：https://coolify.zhuojianai.com，Application jwbpxybciypgdidyzu2ebrlr；Registry-first 手动部署。

跨仓库影响：读取部署规则 7bee0b9 和组织 ai-platform 卡片。此批仅改平台内部持久请求校验，不删接口、不改契约版本或请求/响应 Schema，不修改外部 Skill 或子系统。历史下游退役提示不属于本次新增改动。
