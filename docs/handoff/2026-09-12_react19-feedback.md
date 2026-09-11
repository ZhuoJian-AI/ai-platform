# React 19 静态反馈兼容修复

- 根因：React 19 已移除 react-dom 的 render/createRoot 旧导出；锁定的 Ant Design 5 依赖仍从该出口渲染静态 message/notification/modal。调用可能不抛业务错误但不渲染，解释了语音权限提示消失。
- 依据：https://5x-ant-design.antgroup.com/docs/react/v5-for-19-cn 。使用官方 unstableSetRender 接口注册 react-dom/client createRoot，入口先加载；不升级 UI 库、不新增依赖、不修改权限或业务 Action。
- 候选组件验证：message 展示与销毁、notification 展示、确认弹窗取消不调用 onOk、再次显示消息全部通过。测试只操作组件，无业务写入；前几次脚本失败是动态 import 模块身份及隐藏标题/按钮选择器问题，已修正，未为此修改产品逻辑。
- npm run typecheck、npm run build 通过。录音 ASR/OSS 复用上一批验收，不重复调用模型。
- 测试脚本 frontend/scripts/e2e-antd-feedback.mjs 仅面向本地 Vite 候选环境。
- 此提交是 source；上线后需验证 zhangsan 点击录音时真实显示权限提示且不开麦。朗读、沉浸式语音仍未交付。
