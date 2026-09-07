# 企业级业务小助手语义编排发布

## 发布范围

- 产品源提交：`087368c1374f22a3f1d3d8267182f69ce24b0c60`
- 目标：`https://ai-platform.staging.zhuojianai.com`
- 仅更新 SaaS 后端共用镜像和前端镜像；不包含数据库结构变更。

## 镜像

- 后端旧 digest：`sha256:9ace455979c68614dc3721e18fddaaff245d0cc951e7fcb0547bb530310f3ddf`
- 后端新 digest：`sha256:bf150891e7abc4501cb5accf3ed794328b08996d85fc2f0e75b09be7d9a668d4`
- 前端旧 digest：`sha256:0610e79af632e90746af2bc547fc64a0b73ad6b7da1a242deafcb022f203af8e`
- 前端新 digest：`sha256:62500ff13382fcb8dca9d907561f4f422730bb904b9d77eed71aae2419b106cc`
- 新镜像 OCI revision 均已核对为产品源提交。

## 发布后验证

- 核对所有使用后端共用镜像的服务和前端服务健康。
- 使用真实员工完成页面说明、实时查询、同对话跨页面指代、新对话隔离、历史对话恢复和文件交付回归。
- 核对文件产物真实进入工作空间，并可预览、下载。
- 核对子系统 iframe 无整页闪烁刷新。

## 回退

- 应用异常时只恢复上述旧镜像 digest，不回滚数据库。
