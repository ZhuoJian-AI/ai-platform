import { useState, type CSSProperties, type ReactNode } from 'react';
import { ConfigProvider, Input, Typography, Empty, Spin } from 'antd';
import { RightOutlined } from '@ant-design/icons';
import { WB, WB_FONT, FS, antdTheme } from './theme';

/* ── FinderShell：外层容器 + 嵌套 ConfigProvider ───────────────────────
   嵌套 ConfigProvider 复用 antdTheme（紧凑 macOS 风：靛蓝主色 / 圆角 8 /
   WB_FONT / 13 / 控件高 28），让资源页内 antd 组件与 Finder 原语密度一致，
   不影响 admin 外壳与其它非 Finder 页。 */
export function FinderShell({ children, background = '#fff', style }: {
  children: ReactNode; background?: string; style?: CSSProperties;
}) {
  return (
    <ConfigProvider theme={antdTheme}>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background, ...style }}>
        {children}
      </div>
    </ConfigProvider>
  );
}

/* ── 顶部标题栏 ─────────────────────────────────────────────────────── */
/* titleExtra：紧贴标题右侧的内联区（如组织选择器）；
   extra：被推到顶栏最右端的操作区（如新建按钮）。 */
export function TitleBar({ icon, title, titleExtra, extra }: {
  icon: ReactNode; title: ReactNode; titleExtra?: ReactNode; extra?: ReactNode;
}) {
  return (
    <div style={titleBarStyle}>
      <span style={{ display: 'inline-flex', color: WB.primary, fontSize: 16 }}>{icon}</span>
      <span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>{title}</span>
      {titleExtra !== undefined && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>{titleExtra}</div>
      )}
      {extra !== undefined && (
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>{extra}</div>
      )}
    </div>
  );
}

/* ── 侧栏 ───────────────────────────────────────────────────────────── */
export function Sidebar({ header, children, style }: {
  header?: ReactNode; children: ReactNode; style?: CSSProperties;
}) {
  return (
    <aside style={{ ...sidebarStyle, ...style }}>
      {header !== undefined && <div style={sidebarHeaderStyle}>{header}</div>}
      {children}
    </aside>
  );
}

/* ── MacTree：通用递归树（支持任意深度 / 多分支） ──────────────────── */
export interface FinderTreeNode {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  /** 行右侧小标签（scope 等），不传则不渲染 */
  pill?: ReactNode;
  /** 不可选节点（如「无工作空间」），默认 true */
  selectable?: boolean;
  children?: FinderTreeNode[];
}

export function MacTree({ nodes, selectedKey, onSelect, defaultExpandAll = true }: {
  nodes: FinderTreeNode[];
  selectedKey?: string | null;
  onSelect?: (key: string) => void;
  defaultExpandAll?: boolean;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() =>
    new Set(defaultExpandAll ? flattenKeys(nodes) : []),
  );
  const toggle = (key: string) => setExpanded((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const renderNode = (node: FinderTreeNode, level: number): ReactNode => {
    const hasChildren = !!node.children?.length;
    const isOpen = expanded.has(node.key);
    const active = selectedKey === node.key;
    const selectable = node.selectable !== false;
    return (
      <div key={node.key}>
        <div
          onClick={() => { if (selectable && onSelect) onSelect(node.key); }}
          onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
          onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
          style={treeRowStyle(active, level)}
        >
          <span style={{ width: 12, display: 'inline-flex', justifyContent: 'center', flex: '0 0 12px' }}>
            {hasChildren && (
              <RightOutlined
                onClick={(e) => { e.stopPropagation(); toggle(node.key); }}
                style={{ fontSize: 9, color: WB.textAux, cursor: 'pointer', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}
              />
            )}
          </span>
          {node.icon !== undefined && (
            <span style={{ fontSize: FS.title, color: active ? WB.primary : WB.textAux, flex: '0 0 auto' }}>{node.icon}</span>
          )}
          <span style={{
            flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400,
          }}>{node.label}</span>
          {node.pill !== undefined && <span style={scopePillStyle}>{node.pill}</span>}
        </div>
        {hasChildren && isOpen && node.children!.map((c) => renderNode(c, level + 1))}
      </div>
    );
  };
  if (nodes.length === 0) {
    return <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>暂无节点</div>;
  }
  return <div style={{ padding: '2px 0' }}>{nodes.map((n) => renderNode(n, 0))}</div>;
}

function flattenKeys(nodes: FinderTreeNode[]): string[] {
  const out: string[] = [];
  const walk = (ns: FinderTreeNode[]) => {
    for (const n of ns) {
      if (n.children?.length) { out.push(n.key); walk(n.children); }
    }
  };
  walk(nodes);
  return out;
}

/* ── 工具条 / 路径栏 / 按钮 ─────────────────────────────────────────── */
export function Toolbar({ left, right }: { left: ReactNode; right?: ReactNode }) {
  return (
    <div style={toolbarStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>{left}</div>
      {right !== undefined && <div style={{ display: 'flex', gap: 8 }}>{right}</div>}
    </div>
  );
}

export function PathBar({ rootLabel, rootIcon, segs, onSeg }: {
  rootLabel: ReactNode; rootIcon?: ReactNode; segs: string[]; onSeg: (index: number) => void;
}) {
  return (
    <div style={pathBarStyle}>
      <span className="wb-path-seg" onClick={() => onSeg(-1)} style={pathSegStyle}>
        {rootIcon !== undefined ? <span style={{ marginRight: 4, display: 'inline-flex' }}>{rootIcon}</span> : null}
        {rootLabel}
      </span>
      {segs.map((seg, i) => (
        <span key={i} style={{ display: 'inline-flex', alignItems: 'center' }}>
          <RightOutlined style={{ fontSize: 9, color: '#b0b0b5', margin: '0 2px' }} />
          <span className="wb-path-seg" onClick={() => onSeg(i)} style={pathSegStyle}>{seg}</span>
        </span>
      ))}
    </div>
  );
}

export function NavButton({ icon, disabled, onClick, title }: {
  icon: ReactNode; disabled?: boolean; onClick?: () => void; title?: string;
}) {
  return (
    <button style={navBtnStyle(!!disabled)} disabled={disabled} onClick={onClick} title={title}>{icon}</button>
  );
}

export function ToolButton({ icon, children, onClick, disabled, danger, primary }: {
  icon?: ReactNode; children?: ReactNode; onClick?: () => void; disabled?: boolean;
  danger?: boolean; primary?: boolean;
}) {
  const style: CSSProperties = { ...toolBtnStyle };
  if (primary) { style.background = WB.primary; style.color = '#fff'; style.border = 'none'; }
  if (danger) { style.color = WB.danger; }
  return (
    <button style={style} disabled={disabled} onClick={onClick}>
      {icon !== undefined && <span style={{ display: 'inline-flex' }}>{icon}</span>}
      {children}
    </button>
  );
}

/* ── 图标网格 ───────────────────────────────────────────────────────── */
export function FinderGrid({ children }: { children: ReactNode }) {
  return <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{children}</div>;
}

export function IconCard({ onClick, children, actions }: {
  onClick?: () => void; children: ReactNode; actions?: (hover: boolean) => ReactNode;
}) {
  const [hover, setHover] = useState(false);
  return (
    <div
      style={iconCardStyle(hover)}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92 }}>
        {actions?.(hover)}
        {children}
      </div>
    </div>
  );
}

export function IconActionButton({ icon, variant = 'default', onClick, title }: {
  icon: ReactNode; variant?: 'default' | 'danger'; onClick?: (e: React.MouseEvent) => void; title?: string;
}) {
  return (
    <button style={iconActionBtnStyle(variant)} onClick={onClick} title={title}>{icon}</button>
  );
}

export function IconName({ children }: { children: ReactNode }) {
  return <div style={iconNameStyle}>{children}</div>;
}

/* ── 空态 / 加载 ────────────────────────────────────────────────────── */
export function FinderEmpty({ description }: { description: ReactNode }) {
  return (
    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />
    </div>
  );
}

export function FinderLoading() {
  return <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spin /></div>;
}

/* ── 单文本输入弹窗（新建文件夹 / 重命名 等，MacOS 风） ────────────── */
export function FinderPromptModal(props: {
  open: boolean; title: ReactNode; placeholder?: string;
  value: string; setValue: (v: string) => void;
  /** 输入框后缀（如目标路径预览） */
  suffix?: ReactNode;
  composingRef: { current: boolean };
  loading?: boolean;
  okText?: string;
  onCancel: () => void; onOk: () => void;
}) {
  const { open, title, placeholder, value, setValue, suffix, composingRef, loading, okText = '创建', onCancel, onOk } = props;
  if (!open) return null;
  return (
    <div style={modalOverlayStyle} onClick={onCancel}>
      <div style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: FS.body, fontWeight: 600, color: WB.text, borderBottom: `1px solid ${WB.border}` }}>{title}</div>
        <div style={{ padding: '18px' }}>
          <Input
            autoFocus
            placeholder={placeholder}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setValue((e.target as HTMLInputElement).value); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              onOk();
            }}
            style={{ fontSize: FS.body }}
            suffix={suffix ?? undefined}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={onCancel}>取消</button>
          <button style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }} disabled={loading} onClick={onOk}>
            {loading ? `${okText}中…` : okText}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── 共享样式常量（与终端 WorkspaceManagerView 逐字对齐） ────────────── */
export const titleBarStyle: CSSProperties = {
  height: 44, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 8,
  borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', background: WB.titleBarBg,
};

export const sidebarStyle: CSSProperties = {
  flex: 2, minWidth: 188, maxWidth: 264, background: WB.sidebar,
  borderRight: `1px solid ${WB.border}`, overflowY: 'auto', padding: '8px 0',
};

export const sidebarHeaderStyle: CSSProperties = {
  fontSize: FS.micro, fontWeight: 600, color: WB.textAux, letterSpacing: 0.4,
  textTransform: 'uppercase', padding: '6px 14px 4px',
};

export const treeRowStyle = (active: boolean, level: number): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 6, height: 30,
  margin: '1px 6px', padding: '0 8px', borderRadius: 6, cursor: 'pointer',
  fontSize: FS.body, lineHeight: 1, userSelect: 'none',
  paddingLeft: 8 + level * 16,
  background: active ? WB.activeBg : 'transparent',
  color: active ? WB.primary : WB.text,
  fontWeight: active ? 600 : 400,
});

export const scopePillStyle: CSSProperties = {
  fontSize: 10, color: WB.textAux, background: 'rgba(0,0,0,0.06)',
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

export const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8, flexWrap: 'wrap',
  background: WB.titleBarBg,
};

export const pathBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, overflow: 'hidden',
  background: WB.toolBg, borderRadius: 6, padding: '4px 10px', height: 28,
  fontSize: FS.aux, color: WB.text,
};

export const pathSegStyle: CSSProperties = {
  cursor: 'pointer', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  display: 'inline-flex', alignItems: 'center', borderRadius: 4, padding: '0 2px',
};

export const navBtnStyle = (disabled: boolean): CSSProperties => ({
  width: 28, height: 28, borderRadius: 6, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: FS.aux,
  background: disabled ? 'transparent' : WB.toolBg, color: disabled ? '#c7c7cc' : WB.text,
  flex: '0 0 28px',
});

export const toolBtnStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: FS.aux, color: WB.text,
  background: WB.toolBg, border: 'none', cursor: 'pointer', padding: '5px 10px', borderRadius: 6,
  height: 28,
};

export const iconCardStyle = (hover: boolean): CSSProperties => ({
  width: 108, padding: '10px 6px 8px', borderRadius: 8, cursor: 'default',
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
  border: '1px solid transparent', transition: 'background .12s',
  background: hover ? '#f0f1f4' : 'transparent',
});

export const iconNameStyle: CSSProperties = {
  marginTop: 6, fontSize: FS.aux, color: WB.text, textAlign: 'center',
  overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box',
  WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', width: '100%', lineHeight: 1.3,
};

export const iconActionBtnStyle = (variant: 'default' | 'danger'): CSSProperties => ({
  width: 22, height: 22, borderRadius: 6, border: 'none', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: FS.micro,
  background: 'rgba(255,255,255,0.9)', boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
  color: variant === 'danger' ? WB.danger : WB.text,
});

export const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

export const modalCardStyle: CSSProperties = {
  width: 380, background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};

// 保留 Typography 导入以备个别页直接使用（如文件大小等辅助文本）
export { Typography };
