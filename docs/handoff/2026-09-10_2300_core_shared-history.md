# 跨视图历史通过，实际续问仍待验收

任务：PLATFORM-UNIFIED-ASSISTANT-RUNTIME-E2E-20260910。

## 正向证据

`E2E_EXPLICIT_XLSX=1 node scripts/e2e-staging-core.mjs` 使用独立 Chrome、真实 root/zhangsan 表单登录，在 staging 成功退出 0。新增开关仅将默认请求中的 Excel 明确为 Excel（.xlsx），默认模糊产品名回归仍保留，不能用此代替未发布格式修复的验收。

该次实际下载 XLSX 6854 字节，预览 ready；随后打开同一 Task 总入口深链接，再通过 UI 企业导航返回侧栏，原消息及文件卡片存在，Task ID、文件版本和任务列表一致。测试删除对话 1、文件移入回收站 1，双端正常退出。

这证明的是深链接总入口与页面侧栏的历史恢复，不是用户可见的返回总入口按钮，也不是实际续问已通过。

## 进一步测试

新增在总入口真实输入“刚才生成的文件是什么格式”，要求同一 Task 出现回复、仍保留 Artifact，返回侧栏后显示该续问。

运行 handle 92753 在生成阶段再次失败，尚未到续问：dialogs=0、artifactSections=0，最后 view 始终为 application，没有跳到其它主页面。随后进入 finally 清理，但记录本文时进程仍存活且未返回清理结果。后续必须先轮询同一 handle，不可直接重开测试或声称清理成功。同期目标首页独立 HTTP 检查返回 200，不能因此推断 API 或清理已恢复。

增加下次失败时的脱敏控制台/接口诊断和既定错误视图标签收集，以判断是否 launch 错误。`node --check` 和 `git diff --check` 通过。本地代码尚未部署，目标未完成。
