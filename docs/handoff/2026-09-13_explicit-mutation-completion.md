# 业务修改完成证据

原实现以 ok=true 且状态不在失败列表判断修改已完成。列表没有覆盖 executing、expired、rejected、未知或缺失状态，存在误计成功路径。

改为业务修改必须 ok=true 且 status=completed。查询和文件组合工具的既有返回协议不变，不放宽或收紧模型参数 Schema。允许本轮先失败/未知，再获得明确 completed；确认待处理仍显示等待确认。

验证：`python -m pytest --noconftest tests/test_assistant_runner.py -k write_requires_completed -q`，30 passed、71 deselected；Ruff 通过。测试使用实际事件消费器，覆盖 15 种非完成状态各自不恢复/随后恢复的分支。仅聚焦测试，未重复全量测试或真人端到端。

代码完成、尚未部署；无数据库、前端、外部契约改动。此补丁只校准业务修改完成计数，完整多目标状态及跨轮逻辑操作去重仍未完成。部署规则版本 052b21a。
