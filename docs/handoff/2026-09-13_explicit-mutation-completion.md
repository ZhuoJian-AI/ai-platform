# 业务修改完成证据

原实现以 ok=true 且状态不在失败列表判断修改已完成。列表没有覆盖 executing、expired、rejected、未知或缺失状态，存在误计成功路径。

改为业务修改必须 ok=true 且 status=completed。查询和文件组合工具的既有返回协议不变，不放宽或收紧模型参数 Schema。允许本轮先失败/未知，再获得明确 completed；确认待处理仍显示等待确认。

验证：`python -m pytest --noconftest tests/test_assistant_runner.py -k write_requires_completed -q`，30 passed、71 deselected；Ruff 通过。测试使用实际事件消费器，覆盖 15 种非完成状态各自不恢复/随后恢复的分支。仅聚焦测试，未重复全量测试或真人端到端。

2026-09-13 已部署；无数据库、前端、外部契约改动。此补丁只校准业务修改完成计数，完整多目标状态及跨轮逻辑操作去重仍未完成。部署规则版本 052b21a。

发布证据：

- 仓库 ZhuoJian-AI/ai-platform；域名 https://ai-platform.staging.zhuojianai.com；Coolify Application `jwbpxybciypgdidyzu2ebrlr`。
- source `154f03d293e468ace7789a9f8b479be9f70993b6`（PR #169），manifest `08b0fe1f94b30c23221110eef40e42add7eb0e87`（PR #170）。
- backend/shared worker digest `sha256:af62c5e501881dd0b263cef786201f2205652b08d9e4b033a03a3a889f9e3987`，运行镜像与 OCI source 已核对；前端保留 `28dcfbd`。
- Registry-first 镜像 compileall、Compose 校验通过；真实必填配置和共享令牌一致，无并行部署或待提交配置。部署 `voicefix65c287ceb626a836` finished，9 服务 healthy。
- 公开 health、root 现有浏览器页面、auth/me 均 200；仅会话冒烟，不宣称员工完整业务恢复验收。
- 无数据库迁移，不额外备份；OSS 链路未改，不重复存储测试。已清理本批明确生成的本地与 /tmp 临时构建文件，可从源码重建；镜像及用户数据均保留。
