import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Typography, Empty, Spin, Tooltip, Drawer, Tag } from 'antd';
import {
  ApiOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  EyeOutlined, RightOutlined,
} from '@ant-design/icons';
import { useQuery } from '@tanstack/react-query';
import {
  terminal, type KbNode, type DataSystem, type DataInterface,
} from '../../api/client';

/** WorkBuddy 配色（与 KnowledgeBaseView 一致）。 */
const WB = {
  primary: '#6366F1', sidebar: '#F5F5F7', hover: '#ECECEF', border: '#E5E7EB',
  macFolder: '#5AC8FA', macFile: '#6366F1',
};
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const SCOPE_LABEL: Record<string, string> = {
  organization: '组织', department: '部门', team: '团队', user: '个人',
};
const SCOPE_ICON: Record<string, ReactNode> = {
  organization: <BankOutlined />, department: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};

interface TreeNode {
  key: string;
  name: string;
  scope: string;
  scopeId: string | null;
  children?: TreeNode[];
}

/** 把后端单链 KbNode[] 组装成 组织→部门→团队→个人 嵌套树（每级至多一个）。 */
function buildTree(nodes: KbNode[]): TreeNode[] {
  let child: TreeNode | null = null;
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const node: TreeNode = {
      key: `${n.scope_type}:${n.scope_id ?? ''}`,
      name: n.name, scope: n.scope_type, scopeId: n.scope_id,
      children: child ? [child] : undefined,
    };
    child = node;
  }
  return child ? [child] : [];
}

/** 终端「数据接口」视图：左中右三栏（参照知识库样式）。
 *  左栏：用户可见作用域单链（组织/部门/团队/个人）；中栏：选中 scope 下的数据系统（无操作）；
 *  右栏：选中系统下的数据接口，点击「查看」图标弹出右侧抽屉显示输入输出样例。终端只读。 */
export default function DataInterfaceView() {
  const [scope, setScope] = useState<{ type: string; id: string | null; name: string } | null>(null);
  const [selectedSystem, setSelectedSystem] = useState<DataSystem | null>(null);
  const [viewIface, setViewIface] = useState<DataInterface | null>(null);

  // 左栏 scope 链
  const { data: kbNodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['kb-nodes'], queryFn: () => terminal.kbNodes(),
  });
  const treeData = useMemo(() => buildTree(kbNodes ?? []), [kbNodes]);

  // 默认选中个人节点
  useEffect(() => {
    if (scope || !kbNodes?.length) return;
    const userNode = kbNodes.find((n) => n.scope_type === 'user');
    if (userNode) setScope({ type: userNode.scope_type, id: userNode.scope_id, name: userNode.name });
  }, [kbNodes, scope]);

  // 中栏：选中 scope 下的数据系统
  const { data: systems, isLoading: sysLoading } = useQuery({
    queryKey: ['terminal-data-systems', scope?.type, scope?.id],
    queryFn: () => terminal.listDataSystems({ scope_type: scope!.type, scope_id: scope!.id }),
    enabled: !!scope,
  });

  // 右栏：选中系统下的数据接口
  const { data: ifaces, isLoading: ifLoading } = useQuery({
    queryKey: ['terminal-data-interfaces', selectedSystem?.id],
    queryFn: () => terminal.listDataInterfaces(selectedSystem!.id),
    enabled: !!selectedSystem,
  });

  // 切换系统时关闭样例抽屉
  useEffect(() => { setViewIface(null); }, [selectedSystem?.id]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <ApiOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>数据接口</span>
        <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>
          {scope ? `${scope.name} · ${SCOPE_LABEL[scope.type]}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 2:3:7 三栏主体 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：作用域树 */}
        <aside style={sidebarStyle}>
          <div style={sidebarHeaderStyle}>组织架构</div>
          {nodesLoading ? (
            <div style={{ padding: 16, textAlign: 'center' }}><Spin /></div>
          ) : treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: '#86868b', fontSize: 12 }}>暂无可访问的作用域</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={scope ? `${scope.type}:${scope.id ?? ''}` : null}
              onSelect={(type, id, name) => { setSelectedSystem(null); setScope({ type, id, name }); }}
            />
          )}
        </aside>

        {/* 中栏：系统列表（无操作） */}
        <section style={midPaneStyle}>
          <div style={midToolbarStyle}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#1d1d1f' }}>
              系统 {systems?.length ? `(${systems.length})` : ''}
            </span>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }} className="wb-scroll-hide">
            {!scope ? (
              <PaneEmpty text="请从左侧选择作用域节点" />
            ) : sysLoading ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : !systems?.length ? (
              <PaneEmpty text="该作用域下暂无数据系统" />
            ) : (
              systems.map((s) => {
                const active = selectedSystem?.id === s.id;
                return (
                  <div
                    key={s.id}
                    onClick={() => setSelectedSystem(s)}
                    style={midItemStyle(active)}
                  >
                    <ApiOutlined style={{ fontSize: 16, color: active ? WB.primary : WB.macFolder, flex: '0 0 auto' }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Typography.Text ellipsis style={{ fontSize: 13, color: active ? WB.primary : '#1d1d1f', fontWeight: active ? 600 : 400 }}>{s.name}</Typography.Text>
                      <div>
                        <Typography.Text type="secondary" ellipsis style={{ fontSize: 11 }}>{s.description || '—'}</Typography.Text>
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* 右栏：数据接口列表 + 查看输入输出样例 */}
        <section style={{ flex: 7, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff', borderLeft: `1px solid ${WB.border}` }}>
          {!selectedSystem ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请从中栏选择数据系统" />
            </div>
          ) : (
            <>
              <div style={toolbarStyle}>
                <span style={{ fontSize: 12, fontWeight: 600, color: '#1d1d1f' }}>
                  数据接口 {ifaces?.length ? `(${ifaces.length})` : ''}
                </span>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>点击「查看」查看输入输出样例</Typography.Text>
              </div>

              <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }} className="wb-scroll-hide">
                {ifLoading ? (
                  <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
                ) : !ifaces?.length ? (
                  <PaneEmpty text="该系统下暂无数据接口" />
                ) : (
                  ifaces.map((i) => (
                    <div key={i.id} style={rowStyle}>
                      {i.method ? <Tag color="blue" style={{ marginInlineEnd: 6 }}>{i.method}</Tag> : <ApiOutlined style={{ fontSize: 16, color: WB.macFile, flex: '0 0 auto' }} />}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <Typography.Text ellipsis style={{ fontSize: 13, color: '#1d1d1f' }}>{i.name}</Typography.Text>
                        <div>
                          <Typography.Text type="secondary" ellipsis style={{ fontSize: 11 }}>{i.path || '—'}</Typography.Text>
                        </div>
                      </div>
                      {!i.is_active && <Tag style={{ marginInlineEnd: 6 }}>未启用</Tag>}
                      <div style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                        <IconAction title="查看输入输出样例" icon={<EyeOutlined />} onClick={() => setViewIface(i)} />
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 输入输出样例抽屉（右侧） */}
      <Drawer
        title={viewIface ? `输入输出样例 · ${viewIface.name}` : '输入输出样例'}
        placement="right" open={!!viewIface} width={560}
        onClose={() => setViewIface(null)}
        styles={{ body: { padding: '16px 20px', background: '#fbfbfd' } }}
      >
        {viewIface && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <Typography.Text type="secondary" style={secLabelStyle}>方法 / 路径</Typography.Text>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {viewIface.method ? <Tag color="blue">{viewIface.method}</Tag> : <Tag>—</Tag>}
                <Typography.Text code style={{ fontSize: 12 }}>{viewIface.path || '—'}</Typography.Text>
              </div>
            </div>
            {viewIface.description && (
              <div>
                <Typography.Text type="secondary" style={secLabelStyle}>说明</Typography.Text>
                <Typography.Paragraph style={{ margin: 0, fontSize: 13 }}>{viewIface.description}</Typography.Paragraph>
              </div>
            )}
            <div>
              <Typography.Text type="secondary" style={secLabelStyle}>输入参数样例（params_schema）</Typography.Text>
              <pre style={preStyle}>{JSON.stringify(viewIface.params_schema ?? {}, null, 2)}</pre>
            </div>
            <div>
              <Typography.Text type="secondary" style={secLabelStyle}>输出响应样例（response_schema）</Typography.Text>
              <pre style={preStyle}>{JSON.stringify(viewIface.response_schema ?? {}, null, 2)}</pre>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}

// ── MacOS 风格作用域树（与知识库视图同款单链树） ────────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (type: string, id: string | null, name: string) => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(nodes.map((n) => n.key)));
  const toggle = (key: string) => setExpanded((s) => {
    const next = new Set(s);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });
  const renderNode = (node: TreeNode, level: number): ReactNode => {
    const hasChildren = !!node.children?.length;
    const isOpen = expanded.has(node.key);
    const active = selectedKey === node.key;
    return (
      <div key={node.key}>
        <div
          onClick={() => onSelect(node.scope, node.scopeId, node.name)}
          onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
          onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
          style={treeRowStyle(active, level)}
        >
          <span style={{ width: 12, display: 'inline-flex', justifyContent: 'center', flex: '0 0 12px' }}>
            {hasChildren && (
              <RightOutlined
                onClick={(e) => { e.stopPropagation(); toggle(node.key); }}
                style={{ fontSize: 9, color: '#86868b', cursor: 'pointer', transform: isOpen ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}
              />
            )}
          </span>
          <span style={{ fontSize: 14, color: active ? WB.primary : '#86868b', flex: '0 0 auto' }}>{SCOPE_ICON[node.scope]}</span>
          <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: active ? WB.primary : '#1d1d1f', fontWeight: active ? 600 : 400 }}>{node.name}</span>
          <span style={scopePillStyle}>{SCOPE_LABEL[node.scope]}</span>
        </div>
        {hasChildren && isOpen && node.children!.map((c) => renderNode(c, level + 1))}
      </div>
    );
  };
  return <div style={{ padding: '2px 0' }}>{nodes.map((n) => renderNode(n, 0))}</div>;
}

function PaneEmpty({ text }: { text: string }) {
  return (
    <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 40 }}>
      {text}
    </div>
  );
}

function IconAction(props: { title: string; icon: ReactNode; onClick: () => void }) {
  const { title, icon, onClick } = props;
  const btn = (
    <button style={iconActionBtnStyle} onClick={onClick}>{icon}</button>
  );
  return <Tooltip title={title}>{btn}</Tooltip>;
}

// ── 共享样式 ─────────────────────────────────────────────────────────────

const titleBarStyle: CSSProperties = {
  height: 44, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 8,
  borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', background: '#fbfbfd',
};

const sidebarStyle: CSSProperties = {
  flex: 2, minWidth: 188, maxWidth: 264, background: WB.sidebar,
  borderRight: `1px solid ${WB.border}`, overflowY: 'auto', padding: '8px 0',
};

const sidebarHeaderStyle: CSSProperties = {
  fontSize: 11, fontWeight: 600, color: '#86868b', letterSpacing: 0.4,
  textTransform: 'uppercase', padding: '6px 14px 4px',
};

const treeRowStyle = (active: boolean, level: number): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 6, height: 30,
  margin: '1px 6px', padding: '0 8px', borderRadius: 6, cursor: 'pointer',
  fontSize: 13, lineHeight: 1, userSelect: 'none',
  paddingLeft: 8 + level * 16,
  background: active ? '#E8EAFE' : 'transparent',
  color: active ? WB.primary : '#1d1d1f',
  fontWeight: active ? 600 : 400,
});

const scopePillStyle: CSSProperties = {
  fontSize: 10, color: '#86868b', background: 'rgba(0,0,0,0.06)',
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const midPaneStyle: CSSProperties = {
  flex: 3, minWidth: 200, display: 'flex', flexDirection: 'column',
  background: '#fff', borderRight: `1px solid ${WB.border}`,
};

const midToolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 14px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', background: '#fbfbfd',
};

const midItemStyle = (active: boolean): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', margin: '1px 6px',
  borderRadius: 6, cursor: 'pointer',
  background: active ? '#E8EAFE' : 'transparent',
});

const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8,
  background: '#fbfbfd',
};

const rowStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6,
  fontSize: 13,
};

const iconActionBtnStyle: CSSProperties = {
  width: 26, height: 26, borderRadius: 6, border: 'none', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14,
  background: 'transparent', color: '#1d1d1f',
};

const secLabelStyle: CSSProperties = {
  fontSize: 12, color: '#86868b', display: 'block', marginBottom: 4,
};

const preStyle: CSSProperties = {
  maxHeight: 320, overflow: 'auto', fontSize: 12, background: '#f5f5f5',
  padding: 10, borderRadius: 6, margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
};
