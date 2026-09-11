# 业务与语音收尾：第一批候选修复

## 基线与范围

- 基线：`origin/main` 的 `a6baed957c3acffaef67827653f06e3446f8da9e`。
- 分支：`fix/assistant-voice-reliability-20260911`。
- 独立工作树：`D:/Agent_Project/ai-platform-voice-reliability-20260911`。
- 任务认领：`44f4132`。未覆盖其他工作树或修改外部 Skill、业务子系统。
- 本批已合并并部署，见下方最终发布记录；不代表整个计划完成。

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

## 初次验收遇到的问题（已由后续记录补齐）

- `--noconftest` 仅用于纯测试，不是数据库集成验收。
- 混合测试集中的 `test_workspace_permission_scope.py` 有 3 项、`test_agent_file_references.py` 有 12 项因缺少数据库 fixture 未运行；不能计为通过。
- 本机 Docker 引擎未可用；已隐藏启动 Docker Desktop，但查询仍报 Linux engine 管道不存在。不得改用正式业务数据库执行建表/删表测试。
- 候选分支未做真实管理员、员工浏览器回归，未构建、合并或部署。

## 后续工作

### 最终发布记录

- Source：`9b00713cb536cd821572522dc584b8b8f116830d`（PR #116）。
- Manifest：`110f2781aceeecebfa95727369fb1e2511b06ecb`（PR #117）。
- 后端 digest：`sha256:0904ede643ad72c47b5da69ae2248e56b563ca57cad5227bd5a2ab5868e0a289`。
- Coolify：`jwbpxybciypgdidyzu2ebrlr`；部署 `voicefix7bf6193b6ed77898` 已 finished，无 Changes pending。
- 域名：`https://ai-platform.staging.zhuojianai.com`。9 个服务全部 healthy，4 个使用后端镜像的服务 digest 一致，调用端/服务端共享令牌一致（未输出原文）。
- 上线后的全新浏览器隔离上下文：root 登录及工作空间目录通过；zhangsan 登录及个人空间文件视图通过；未出现 5xx。未伪造 Token/Cookie，未新增或删除业务文件、未修改角色。
- 无数据库迁移、无前端产物变化、无 OSS 链路变更；因此复用既有存储验收，不重复全量测试。
- 临时 PostgreSQL、额外测试容器和测试网络已删除；仅丢弃可重建的测试数据。未清理线上卷、其他项目、旧回切镜像，未初始化 `/dev/vdb`。
- 部署规则版本：`c948cd2`。Compose 入口、真实环境变量预检 PASS。
- 录音回填、按需朗读、沉浸式语音，以及未知写入核实/历史 401 调查仍待后续实施。

### 后续验收更新

- Source PR #116 已合并：`9b00713cb536cd821572522dc584b8b8f116830d`。
- Registry 已返回候选后端 digest：`sha256:0904ede643ad72c47b5da69ae2248e56b563ca57cad5227bd5a2ab5868e0a289`；镜像编译检查通过。仅复制代码，无依赖安装或数据库迁移。
- 回切后端 digest：`sha256:84032ed2ee9a9c408385c2b0b937060fe6a7b26ec447416a55f10dde21f2749f`，前端保持原 digest。

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
