# 部分结果提示与回执证据

本批接续 PR #144（`d54db08`），仅发布实际具备的结果提示能力。

- 辅助查询成功、业务修改未取得成功回执时，分别说明查询与修改状态。
- 有明确 `completed` 写入回执但文件交付失败时，保留业务成功事实，提示仅继续未完成的文件。
- 缺失状态、待确认、未知、失败及拒绝结果不能推断成成功。
- PR #144 没有新增完整跨轮自动恢复；此前“重新生成文件不会重复执行”的绝对承诺已改为恢复范围提示。现有确认及幂等机制继续保留，完整多目标恢复仍待实施。

验证：Python 3.12 运行 `pytest --noconftest tests/test_assistant_policy.py tests/test_assistant_runner.py -k 'artifact or auxiliary_query or write_requires' -q`，52 passed；聚焦 Ruff 通过。覆盖不完整回执、文件失败、辅助查询和确认/重试路径。

发布前状态：代码候选；没有数据库迁移、依赖、前端或 OSS 链路变化。上线后补充 source、镜像、manifest 和 Coolify 证据。历史运行 401、长文本语义口播和真实账号专项限制仍未解决。
