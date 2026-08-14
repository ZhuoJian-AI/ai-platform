/** Finder 设计令牌：与终端门户 WB / WB_FONT / 紧凑字号梯逐字一致。
 *  管理端资源页统一引用本模块，保证与终端的配色 / 字体 / 密度对齐。 */
import type { ThemeConfig } from 'antd';

/** WorkBuddy 配色（参考 Terminal.tsx 的 tailwind theme）。 */
export const WB = {
  primary: '#6366F1',
  primaryHover: '#818CF8',
  sidebar: '#F5F5F7',
  hover: '#ECECEF',
  border: '#E5E7EB',
  macFolder: '#5AC8FA',
  macFile: '#6366F1',
  /** 文本主色 / 辅助灰阶（macOS Finder 风） */
  text: '#1d1d1f',
  textAux: '#86868b',
  textMicro: '#aeaeb2',
  activeBg: '#E8EAFE',
  toolBg: '#eef0f3',
  titleBarBg: '#fbfbfd',
  danger: '#ff3b30',
};

/** 统一字体栈：含中文回退字体（PingFang SC / Microsoft YaHei）。 */
export const WB_FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

/** 紧凑字号梯（与终端一致；均以 inline fontSize 应用，不走 ConfigProvider）。 */
export const FS = {
  title: 14, // 标题
  body: 13, // 主文本
  aux: 12, // 辅助
  micro: 11, // 微辅助
} as const;

/** 管理端 antd 紧凑 macOS 主题：统一作用于 App 外壳与 FinderShell 的 ConfigProvider。
 *  在不改各页 JSX 的前提下，让 Button / Input / Select / Table / Modal / Form / Card /
 *  Statistic 全部收敛为 Finder 风：字号 12–13、控件高 28、圆角 6–8、表格行紧凑、弹窗字号收紧。
 *  antd 5.24 支持下列全部 token。 */
export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: WB.primary, colorPrimaryHover: WB.primaryHover,
    colorBorder: WB.border, colorText: 'rgba(0, 0, 0, 0.88)',
    colorTextSecondary: WB.textAux,
    fontFamily: WB_FONT, fontSize: FS.body, // 13 全局基础字号
    borderRadius: 8,
    controlHeight: 28, controlHeightSM: 24,
    paddingXS: 8, paddingSM: 12, padding: 12, paddingLG: 16,
    marginXS: 8, marginSM: 12,
  },
  components: {
    Button: {
      controlHeight: 28, controlHeightSM: 24, paddingInline: 12, paddingInlineSM: 8,
      fontSize: FS.aux, fontSizeSM: FS.micro, fontWeight: 500, borderRadius: 6,
      primaryShadow: 'none', defaultShadow: 'none',
    },
    Input: { controlHeight: 28, fontSize: FS.body, borderRadius: 6 },
    InputNumber: { controlHeight: 28, fontSize: FS.body, borderRadius: 6 },
    Select: { controlHeight: 28, fontSize: FS.body, borderRadius: 6, optionFontSize: FS.body },
    TreeSelect: { controlHeight: 28, fontSize: FS.body, borderRadius: 6 },
    DatePicker: { controlHeight: 28, fontSize: FS.body, borderRadius: 6 },
    Table: {
      fontSize: FS.body, headerBg: '#fafafa', headerColor: WB.textAux,
      headerSplitColor: WB.border, rowHoverBg: WB.hover, borderColor: WB.border,
      cellPaddingBlock: 8, cellPaddingInline: 12,
    },
    Modal: { titleFontSize: FS.body, fontSize: FS.body, borderRadiusLG: 12 },
    Form: {
      labelFontSize: FS.aux, labelColor: WB.text,
      verticalLabelPadding: '0 0 4px', itemMarginBottom: 14,
    },
    Card: { borderRadiusLG: 8, headerFontSize: FS.body, paddingLG: 14 },
    Tag: { fontSize: FS.micro, borderRadiusSM: 4 },
    Typography: { fontSize: FS.body },
    Statistic: { titleFontSize: FS.aux, contentFontSize: 20 },
    Pagination: { fontSize: FS.aux, itemSize: 24 },
    Divider: { marginLG: 12 },
  },
};
