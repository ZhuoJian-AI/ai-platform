# 恢复回执与后续文件来源衔接

发现：普通业务工具完成后写入 business_action_provenance，文件验证器从中读取业务来源；resume_action 返回原回执后漏写该状态，导致后续文件缺少恢复的原业务来源。

修复：普通调用和恢复调用共用 retain_completed_provenance。只接受 completed 及结构化 provenance，保留原执行时间和快照，恢复路径标记 replayed；相邻相同证据不重复追加，不修改原回执。未完成结果不作为成功来源。没有新建远端写入、没有跳过文件落盘与实时权限校验。

验证：`python -m pytest --noconftest tests/test_assistant_action_recovery.py -q`，30 passed；Ruff 通过。覆盖实际恢复分支的状态传递、原时间、快照、失败/未知/待确认状态隔离。未重新运行全部测试；未进行真实 OSS 文件恢复或员工操作闭环，因此不声明这些验收完成。

状态：2026-09-13 已部署。无数据库、前端、存储协议或外部 Skill 修改。完整多目标状态机、已完成操作的再次调用保护仍未实现。部署规则版本 052b21a。

发布证据：

- 仓库 ZhuoJian-AI/ai-platform；https://ai-platform.staging.zhuojianai.com；Coolify Application `jwbpxybciypgdidyzu2ebrlr`。
- source `964ea676509cb1ea1524d0c6fcab9c265f82b7a3`（PR #166）；manifest `c1b21fa05744a4399775de0475e1737a35eb7d62`（PR #167）。
- backend/shared worker digest `sha256:da8f40bb7ec6e72429b27094c9e1dd2caba786ac7601f468d85863b5fe38d64c`；运行 backend 与 OCI revision 核对一致。前端沿用 `28dcfbd`。
- Registry-first，镜像 compileall、Compose 入口验证 PASS；实际必填环境及共享令牌检查通过，无待提交配置、无并行部署。
- 部署 `voicefix5084fece6af836c8` finished；9 服务 healthy；公开 health 200，root 现有浏览器会话页面及 auth/me 200。该检查不替代员工实际恢复文件验收。
- 无迁移，不额外备份；OSS 链路未变，不重复存储测试。明确生成的本地/服务器临时构建文件已清理，可从源码重建；镜像与用户数据均保留。
