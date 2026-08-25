# AI Platform Extension SDK

本目录是把普通 DSH/Cordis 插件适配成 AI Platform 全局扩展的最小契约。平台级扩展只由超级管理员导入，并且必须经过 Builder、人工审核、候选 Context 验证和不可变发布。

## 支持的两类扩展

- `runtime_plugin`：装配到 DSH Runtime，可新增 Hook、记忆、模型适配器，或替换协调器等明确插槽。
- `system_tool`：向模型注册系统工具 Schema；handler 必须通过平台桥接访问租户数据，不能自行读取数据库或长期密钥。

插件根目录至少包含：

```text
plugin/
├─ ai-platform.extension.json
├─ package.json
└─ index.mjs
```

提交前运行固定版本 pnpm 生成并提交 `pnpm-lock.yaml`；Builder 不接受浮动依赖作为正式候选。

清单格式见 [manifest.schema.json](manifest.schema.json)。可以从 `templates/runtime-plugin` 或 `templates/system-tool` 开始。协调器、记忆/RAG策略和模型适配器若声明 `operation: replace`，同一个候选发布中每个插槽只能有一个提供者。

## Codex 适配流程

1. 在平台插件市场为“需要适配”的条目生成 Markdown 任务。
2. 固定 npm 精确版本或 Git Commit。
3. 添加平台清单、薄适配入口、健康检查和烟雾测试，不重写第三方库。
4. 将适配项目通过 GitHub 或 ZIP 导入 Extension Builder。
5. 构建成功后人工审核，再创建候选发布验证；验证通过才允许全局发布。

平台不会从网页直接修改源码，也不会把未审核社区代码热加载进当前 Runtime。
