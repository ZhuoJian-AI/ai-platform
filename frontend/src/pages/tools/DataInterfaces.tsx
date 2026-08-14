import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Input, Modal, Switch, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, EyeOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { dataInterfaces } from '../../api/client';
import type { DataInterface, DataSystem } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { useOrgTree } from '../../hooks/useOrgTree';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import { WB, FS } from '../../components/finder/theme';

interface ScopeState {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id?: string | null;
  orgId: string;
  nodeName: string;
}

const SCOPE_PREFIX: Record<ScopeState['scope_type'], string> = {
  organization: 'org', department: 'dept', team: 'team', user: 'user',
};
const NODE_ICON: Record<string, ReactNode> = {
  org: <BankOutlined />, dept: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};
const iconForKey = (key: string): ReactNode => NODE_ICON[key.split(':')[0]] ?? <ApiOutlined />;

/** 数据接口页：Finder 风。系统 / 数据接口独立数据结构，仅启用/禁用 + 搜索 + 查看输入输出样例。
 *  左中右三栏：架构树 · 系统 · 数据接口。节点作用域化。 */
export default function DataInterfaces() {
  const qc = useQueryClient();
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const [orgId, setOrgId] = useState<string | undefined>();

  const [scope, setScope] = useState<ScopeState | null>(null);
  const [selectedSystem, setSelectedSystem] = useState<DataSystem | null>(null);
  const [keyword, setKeyword] = useState('');
  const [viewEp, setViewEp] = useState<DataInterface | null>(null);

  const treeDataScoped = useMemo(() => {
    if (!orgId) return [];
    return treeData.filter((n) => n.key === `org:${orgId}`);
  }, [treeData, orgId]);

  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({ key: n.key, label: n.title, icon: iconForKey(n.key), children: n.children?.length ? build(n.children) : undefined }));
    return build(treeDataScoped);
  }, [treeDataScoped]);

  // 选中组织变化（或树首次加载且未选 scope）→ 落到该组织根节点作为默认作用域
  useEffect(() => {
    if (scope || treeLoading || !orgId) return;
    const info = nodeMap.get(`org:${orgId}`);
    if (info) setScope({ scope_type: 'organization', scope_id: null, orgId: info.orgId, nodeName: info.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, treeLoading, treeData]);

  const selectedKey = scope ? `${SCOPE_PREFIX[scope.scope_type]}:${scope.scope_id ?? scope.orgId}` : null;

  const { data: systems, isLoading: sysLoading } = useQuery({
    queryKey: ['data-systems', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => scope
      ? dataInterfaces.listSystems(scope.orgId, { scope_type: scope.scope_type, scope_id: scope.scope_id ?? null })
      : Promise.resolve([]),
    enabled: !!scope,
  });

  const { data: ifaces, isLoading: ifLoading } = useQuery({
    queryKey: ['data-interfaces', selectedSystem?.id],
    queryFn: () => selectedSystem ? dataInterfaces.listInterfaces(selectedSystem.id) : Promise.resolve([]),
    enabled: !!selectedSystem,
  });

  const toggleSystem = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) => dataInterfaces.updateSystem(v.id, { is_active: v.is_active }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['data-systems'] }); message.success('已更新'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '更新失败'),
  });
  const toggleIface = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) => dataInterfaces.updateInterface(v.id, { is_active: v.is_active }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['data-interfaces'] }); message.success('已更新'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '更新失败'),
  });

  const filteredIfaces = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return ifaces ?? [];
    return (ifaces ?? []).filter((i) =>
      (i.name ?? '').toLowerCase().includes(kw) ||
      (i.path ?? '').toLowerCase().includes(kw) ||
      (i.method ?? '').toLowerCase().includes(kw));
  }, [ifaces, keyword]);

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<ApiOutlined />}
        title="数据接口"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setSelectedSystem(null); setScope(null); }} />}
      />

      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：组织架构树 */}
        <Sidebar header="组织架构" style={{ flex: 2, maxWidth: 240 }}>
          {treeLoading ? <FinderLoading /> : finderTree.length === 0 ? (
            <div style={{ padding: '8px 12px', color: WB.textAux, fontSize: FS.aux }}>暂无组织架构</div>
          ) : (
            <MacTree
              nodes={finderTree}
              selectedKey={selectedKey}
              onSelect={(key) => {
                const info = nodeMap.get(key);
                if (!info) return;
                setSelectedSystem(null);
                setScope({ scope_type: info.type, scope_id: info.type === 'organization' ? null : info.id, orgId: info.orgId, nodeName: info.name });
              }}
            />
          )}
        </Sidebar>

        {/* 中栏：系统 */}
        <section style={{ flex: 2, minWidth: 0, display: 'flex', flexDirection: 'column', borderRight: `1px solid ${WB.border}` }}>
          <Toolbar left={<span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>系统</span>} />
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!scope ? (
              <FinderEmpty description="请从左侧选择节点" />
            ) : sysLoading ? <FinderLoading /> : (systems?.length === 0) ? (
              <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>该节点下暂无系统</div>
            ) : (systems ?? []).map((s) => {
              const active = selectedSystem?.id === s.id;
              return (
                <div
                  key={s.id}
                  onClick={() => setSelectedSystem(s)}
                  onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                  onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6, cursor: 'pointer', fontSize: FS.body, lineHeight: 1.3, background: active ? WB.activeBg : 'transparent' }}
                >
                  <ApiOutlined style={{ fontSize: 15, color: active ? WB.primary : WB.macFile, flex: '0 0 auto' }} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400 }}>{s.name}</div>
                    <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.description || '—'}</div>
                  </div>
                  <span onClick={(e) => e.stopPropagation()} style={{ flex: '0 0 auto' }}>
                    <Switch size="small" checked={s.is_active} loading={toggleSystem.isPending && toggleSystem.variables?.id === s.id} onChange={(on) => toggleSystem.mutate({ id: s.id, is_active: on })} />
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        {/* 右栏：数据接口 */}
        <section style={{ flex: 6, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          <Toolbar
            left={<span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>{selectedSystem ? selectedSystem.name : '数据接口'}</span>}
            right={selectedSystem && (
              <Input size="small" allowClear placeholder="搜索名称/路径/方法" style={{ width: 220 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            )}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!selectedSystem ? (
              <FinderEmpty description="请从中栏选择系统" />
            ) : ifLoading ? <FinderLoading /> : filteredIfaces.length === 0 ? (
              <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>此处暂无数据接口</div>
            ) : filteredIfaces.map((i) => (
              <div key={i.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6, fontSize: FS.body, lineHeight: 1.3 }}
                onMouseEnter={(e) => { e.currentTarget.style.background = WB.hover; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}>
                {i.method ? <Tag color="blue" style={{ marginInlineEnd: 0, flex: '0 0 auto' }}>{i.method}</Tag> : null}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{i.name}</div>
                  <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.path || '—'}</div>
                </div>
                <span style={{ display: 'flex', alignItems: 'center', gap: 8, flex: '0 0 auto' }}>
                  <ToolButton icon={<EyeOutlined style={{ fontSize: 13 }} />} onClick={() => setViewEp(i)}>查看</ToolButton>
                  <Switch size="small" checked={i.is_active} loading={toggleIface.isPending && toggleIface.variables?.id === i.id} onChange={(on) => toggleIface.mutate({ id: i.id, is_active: on })} />
                </span>
              </div>
            ))}
          </div>
        </section>
      </div>

      {/* 输入输出样例 */}
      <Modal
        title={`输入输出样例 · ${viewEp?.name ?? ''}`} open={!!viewEp}
        onCancel={() => setViewEp(null)} footer={null} width={720}
      >
        {viewEp && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: FS.aux }}>方法 / 路径</Typography.Text>
              <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
                {viewEp.method ? <Tag color="blue" style={{ marginInlineEnd: 0 }}>{viewEp.method}</Tag> : <Tag>—</Tag>}
                <Typography.Text code>{viewEp.path || '—'}</Typography.Text>
              </div>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: FS.aux }}>输入参数样例（params_schema）</Typography.Text>
              <pre style={preStyle}>{JSON.stringify(viewEp.params_schema ?? {}, null, 2)}</pre>
            </div>
            <div>
              <Typography.Text type="secondary" style={{ fontSize: FS.aux }}>输出响应样例（response_schema）</Typography.Text>
              <pre style={preStyle}>{JSON.stringify(viewEp.response_schema ?? {}, null, 2)}</pre>
            </div>
            {viewEp.description && (
              <div>
                <Typography.Text type="secondary" style={{ fontSize: FS.aux }}>说明</Typography.Text>
                <Typography.Paragraph style={{ margin: 0, fontSize: FS.body }}>{viewEp.description}</Typography.Paragraph>
              </div>
            )}
          </div>
        )}
      </Modal>
    </FinderShell>
  );
}

const preStyle: React.CSSProperties = {
  maxHeight: 280, overflow: 'auto', fontSize: 12, background: '#f5f5f5',
  padding: 8, borderRadius: 4, marginTop: 4,
};
