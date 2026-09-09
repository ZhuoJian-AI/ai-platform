/** User-facing product help. Keep this aligned with the routes that actually ship. */
export interface HelpItem {
  heading: string;
  paragraphs?: string[];
  bullets?: string[];
}

export interface HelpSection {
  id: string;
  title: string;
  items: HelpItem[];
}

export const HELP_SECTIONS: HelpSection[] = [
  {
    id: 'overview', title: '平台简介', items: [
      {
        heading: '这是什么',
        paragraphs: ['企业 AI 底座统一提供模型路由、AI 助手、工作空间、业务应用接入与运行监控。'],
        bullets: [
          '个人助手：通用对话、Web、多模态、长期记忆和平台固定文件工具。',
          '文本智能体：一份可复用的角色提示词，能力与当前用户的个人助手完全一致。',
          '业务小助手：只使用当前页面实时授权的 Manifest Action 与平台文件工具。',
          '专业 AI：由子系统声明专业能力，通过平台受控模型调用执行。',
        ],
      },
    ],
  },
  {
    id: 'roles', title: '角色与权限', items: [
      {
        heading: '管理员角色', bullets: [
          '超级平台管理员可管理全部企业和平台配置。',
          '企业管理员永久绑定一个企业，只能管理本企业资源。',
          '员工通过一个或多个角色获得权限，多角色权限取并集。',
        ],
      },
      {
        heading: '实时鉴权',
        paragraphs: ['工作空间、企业应用页面、Action 和 AI 工具在每次请求时按当前角色重新校验；角色提示词不能扩大权限。'],
      },
    ],
  },
  {
    id: 'organization', title: '企业与员工', items: [
      {
        heading: '组织架构', bullets: [
          '建立企业、部门和员工层级；员工只归属一个主部门。',
          '可为员工配置多个角色并随时启停账号。',
          '企业、部门和个人工作空间随组织节点自动生成和同步。',
        ],
      },
      {
        heading: '员工账号',
        paragraphs: ['员工使用企业专属登录地址、用户名和密码登录。管理员可创建、编辑、重置密码、启停和删除员工。'],
      },
    ],
  },
  {
    id: 'models', title: '模型路由', items: [
      {
        heading: '模型提供商与 API Key', bullets: [
          '模型提供商可绑定企业或部门，部门配置优先、企业配置兜底。',
          '平台 API Key 继承企业与部门的模型范围、速率和额度限制。',
          '供应商密钥加密存储，写入后不再回显明文。',
          '平台不再提供 Embedding 模型注册和专用调用；模型配置只展示仍在使用的对话与多模态能力。',
        ],
      },
      {
        heading: '安全围栏',
        paragraphs: ['按企业或部门配置请求与响应检测，可执行拦截、脱敏、告警或记录。'],
      },
    ],
  },
  {
    id: 'assistant', title: '助手与文本智能体', items: [
      {
        heading: '个人助手', bullets: [
          '选择本轮模型和工作空间，可上传附件或引用有权读取的工作空间文件。',
          '支持连续对话、Web、多模态、长期记忆和平台固定文件工具。',
          '生成的文件提交到工作空间后，以可预览、可下载的文件卡片交付。',
        ],
      },
      {
        heading: '文本智能体', bullets: [
          '只保存名称、说明和角色提示词，不绑定模型、工作空间、应用或可执行代码。',
          '运行时使用用户本轮选择的模型，并继承个人助手的能力和实时权限。',
          '可按企业、部门或个人作用域创建；删除角色不会删除历史对话和文件。',
        ],
      },
      {
        heading: '长期记忆',
        paragraphs: ['长期记忆以 Markdown 文本维护，按企业、部门和个人权限加载；它不授予额外业务权限。'],
      },
    ],
  },
  {
    id: 'workspace', title: '工作空间', items: [
      {
        heading: '文件管理', bullets: [
          '支持文件夹、上传、下载、预览、版本、回收站和恢复。',
          '可预览 Excel、Word、PowerPoint、PDF、图片、音视频和文本。',
          '助手读取和生成文件都经过工作空间实时鉴权，不能越出授权范围。',
          '删除对话不会删除已经交付到工作空间的文件。',
        ],
      },
    ],
  },
  {
    id: 'applications', title: '企业应用与业务 AI', items: [
      {
        heading: '企业应用接入',
        paragraphs: ['业务系统通过 Runtime、Manifest、SSO、Bridge、Action 和 Event 接入平台。'],
        bullets: [
          '业务小助手只获得当前应用、模块和页面中员工实时获权的 Action。',
          '业务凭证由 Runtime 与平台自动处理，员工和模型不接触长期令牌。',
          '业务数据生成文件时，由平台固定文件执行器写入当前员工工作空间。',
          '子系统专业 AI 的声明、输入、输出和模型调用由平台校验和审计。',
        ],
      },
    ],
  },
  {
    id: 'monitor', title: '监控与审计', items: [
      {
        heading: '可观测内容',
        bullets: ['模型路由、助手运行、平台固定工具、业务 Action、延迟、错误、额度和审计日志。'],
      },
    ],
  },
];
