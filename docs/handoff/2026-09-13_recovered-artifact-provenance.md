# 恢复回执与后续文件来源衔接

发现：普通业务工具完成后写入 business_action_provenance，文件验证器从中读取业务来源；resume_action 返回原回执后漏写该状态，导致后续文件缺少恢复的原业务来源。

修复：普通调用和恢复调用共用 retain_completed_provenance。只接受 completed 及结构化 provenance，保留原执行时间和快照，恢复路径标记 replayed；相邻相同证据不重复追加，不修改原回执。未完成结果不作为成功来源。没有新建远端写入、没有跳过文件落盘与实时权限校验。

验证：`python -m pytest --noconftest tests/test_assistant_action_recovery.py -q`，30 passed；Ruff 通过。覆盖实际恢复分支的状态传递、原时间、快照、失败/未知/待确认状态隔离。未重新运行全部测试；未进行真实 OSS 文件恢复或员工操作闭环，因此不声明这些验收完成。

状态：代码完成，尚未部署。无数据库、前端、存储协议或外部 Skill 修改。完整多目标状态机、已完成操作的再次调用保护仍未实现。部署规则沿用本次重新拉取的 052b21a；此文不作为上线证据。
