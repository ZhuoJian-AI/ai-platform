/** Enterprise-admin help: same products as the platform, constrained to one enterprise. */
import type { HelpSection } from './content';

export const HELP_SECTIONS_ORG_ADMIN: HelpSection[] = [
  {
    id: 'overview', title: '企业管理员', items: [
      {
        heading: '你的管理范围',
        paragraphs: ['账号永久绑定当前企业，所有查询、创建和修改都限定在本企业。'],
        bullets: [
          '管理本企业部门、员工、角色和工作空间权限。',
          '管理本企业模型提供商、API Key、安全围栏和额度。',
          '管理文本智能体、长期记忆、企业应用授权和运行监控。',
          '不能访问平台超级管理员或其他企业资源。',
        ],
      },
    ],
  },
  {
    id: 'employees', title: '员工与权限', items: [
      {
        heading: '员工授权', bullets: [
          '员工只归属一个主部门，可以同时绑定多个角色。',
          '多角色权限取并集；权限变更后下一次请求立即按新权限校验。',
          '可创建、编辑、重置密码、启停和删除本企业员工。',
        ],
      },
      {
        heading: '工作空间权限',
        paragraphs: ['个人空间归本人使用；主部门和跨部门空间能力由统一权限服务计算，界面显示必须与接口实际结果一致。'],
      },
    ],
  },
  {
    id: 'assistant', title: '助手与文本智能体', items: [
      {
        heading: '文本智能体',
        paragraphs: ['文本智能体只保存名称、说明和角色提示词，不拥有独立工具、密钥或资源绑定。'],
        bullets: [
          '运行时继承员工个人助手的 Web、多模态、长期记忆、工作空间和平台固定文件工具。',
          '模型由员工在本轮选择，全部能力按当前员工实时权限装配。',
          '提示词不能扩大工作空间、企业应用页面或 Action 权限。',
        ],
      },
      {
        heading: '长期记忆',
        paragraphs: ['长期记忆以 Markdown 文本维护，按企业、部门和个人作用域加载。'],
      },
    ],
  },
  {
    id: 'models', title: '模型与安全', items: [
      {
        heading: '模型提供商',
        paragraphs: ['为企业或部门注册 LLM、多模态、图像和音频模型提供商；部门配置优先、企业配置兜底。'],
      },
      {
        heading: '安全围栏',
        paragraphs: ['按企业或部门配置请求和响应检测，并通过审计与监控查看执行结果。'],
      },
    ],
  },
  {
    id: 'applications', title: '企业应用', items: [
      {
        heading: '业务小助手与专业 AI', bullets: [
          '业务小助手只加载当前页面员工实时获权的 Manifest Action。',
          '专业 AI 由子系统声明能力，平台负责模型调用、权限校验、审计和结果交付。',
          '业务数据生成的文件由平台固定执行器提交员工工作空间。',
          'Runtime、SSO、Bridge、Action 和 Event 保持可用。',
        ],
      },
    ],
  },
  {
    id: 'workspace', title: '工作空间', items: [
      {
        heading: '文件能力',
        paragraphs: ['支持文件夹、上传、预览、下载、版本、回收站、恢复及助手 Artifact 交付，所有操作都进行实时权限校验。'],
      },
    ],
  },
  {
    id: 'monitor', title: '监控', items: [
      {
        heading: '本企业监控',
        paragraphs: ['查看模型、助手、平台固定工具、业务 Action、错误、延迟、额度和审计信息。'],
      },
    ],
  },
];
