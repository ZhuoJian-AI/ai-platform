# 业务与语音收尾：第一批候选修复

## 基线与范围

- 基线：`origin/main` 的 `a6baed957c3acffaef67827653f06e3446f8da9e`。
- 分支：`fix/assistant-voice-reliability-20260911`。
- 独立工作树：`D:/Agent_Project/ai-platform-voice-reliability-20260911`。
- 任务认领：`44f4132`。未覆盖其他工作树或修改外部 Skill、业务子系统。
- 本批未合并、未部署，无新镜像 digest，不代表整个计划完成。

## 已修改

1. 音频理解同步服务不再输出或回退到 `reasoning_content`；无有效正文返回 `empty_response`。
2. 旧音频 SSE 丢弃推理事件；没有有效正文时发送中文可重试错误，不发送成功 `done`。
3. 工作空间统一读写检查要求有效租户和主体；缺失/空字段不再只读放行，权限来源说明也不越过此检查。
4. 公共工具和业务候选采用相同相关性尺度排序，不再将全部业务候选固定前置；只激活实际返回的工具候选。
5. 中文 `AGENTS.md` 增加代码、部署、真实验收的区别及语音边界。

## 已验证

以下命令在 `llm_router/backend` 执行：

```text
python -m pytest --noconftest tests/test_voice_reliability_boundaries.py tests/test_assistant_tool_catalog.py tests/test_native_assistant_core.py tests/test_hybrid_rbac_audio.py -q
69 passed
```

受影响 Python 文件 Ruff 检查通过。覆盖推理泄露、空答案、缺失身份、个人所有权、混合工具发现和已有原生主脑循环。

## 未通过验收门禁的事项

- `--noconftest` 仅用于纯测试，不是数据库集成验收。
- 混合测试集中的 `test_workspace_permission_scope.py` 有 3 项、`test_agent_file_references.py` 有 12 项因缺少数据库 fixture 未运行；不能计为通过。
- 本机 Docker 引擎未可用；已隐藏启动 Docker Desktop，但查询仍报 Linux engine 管道不存在。不得改用正式业务数据库执行建表/删表测试。
- 候选分支未做真实管理员、员工浏览器回归，未构建、合并或部署。

## 后续工作

### 后续验收更新

- 服务器只读检查：系统盘约剩 15GB；`/dev/vdb` 为 60GB，`lsblk` 无文件系统和挂载点、`wipefs -n` 无签名输出。未格式化、分区或挂载。
- 使用独立 PostgreSQL 容器和 512MB tmpfs 数据目录，未使用线上数据库。测试进程复用本项目空闲测试容器，在独立目录运行。
- 正常 conftest 的上述 6 个测试文件共 **98 passed (19.42s)**。初次出现的两个失败源自空身份测试替身；已补齐租户、主体和明确角色授权，未放宽生产校验。
- 候选浏览器使用新建隔离上下文，root、zhangsan 均真实表单登录成功，进入实际工作空间成功，无 5xx；没有修改角色或业务文件。
- 用户要求减少无意义测试：本批不重跑无关全模块回归。浏览器冒烟脚本仅验证登录和工作空间，不能作为语音或全模块验收证据。

1. 建立独立测试数据库，使用正常 conftest 重跑受影响权限及文件调用链；需要投影对象时补齐生产身份字段，不恢复 fail-open。
2. 继续不可用能力中文分类、历史运行 401 证据调查、未知写入受控核实及部分完成状态。
3. 修复录音交互：当前代码仍先上传长期工作空间、等待期间捕获旧输入值，不能将现有文件 ASR 验收当成录音按钮验收。
4. 实施临时媒体、消息绑定朗读，再实现同一 Task 的轮流语音控制；角色不永久扩大。
5. 按原计划聚焦测试与真实角色验收后分批发布 staging。
