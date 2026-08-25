import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Input, Typography, Upload, message, Empty, Spin, Tooltip, Tag } from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  FolderOutlined, FileTextOutlined, EditOutlined, RightOutlined,
  DownOutlined, EyeOutlined, UploadOutlined, SearchOutlined, ThunderboltOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  terminal, type SkillScopeNode, type SkillFolder, type SkillFile, type SkillFileMeta,
} from '../../api/client';
import { ApiError } from '../../api/client';
import ConfirmModal from '../../components/finder/ConfirmModal';

/** WorkBuddy 配色（与 KnowledgeBaseView / WorkspaceManagerView 一致）。 */
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
  canImport: boolean;
  canManage: boolean;
  children?: TreeNode[];
}

/** 负责人可能管理多个并列节点，技能作用域接口因此按节点平铺返回。 */
function buildTree(nodes: SkillScopeNode[]): TreeNode[] {
  return nodes.map((n) => ({
    key: `${n.scope_type}:${n.scope_id ?? ''}`,
    name: n.name,
    scope: n.scope_type,
    scopeId: n.scope_id,
    canImport: n.can_import,
    canManage: n.can_manage,
  }));
}

/** 取路径末段。 */
function leaf(p: string): string {
  return p.includes('/') ? p.slice(p.lastIndexOf('/') + 1) : p;
}

type ConfirmTarget =
  | { kind: 'skill'; id: string; title: string }
  | { kind: 'file'; id: string; title: string };

/** 终端「技能」视图：左右两栏（参照工作空间样式）。
 *  左栏：用户可见作用域单链（组织/部门/团队/个人）；右栏：选中 scope 下的技能操作区。
 *  导入：在可管理 scope 选择标准 Skill 文件夹或上传 ZIP/MD；智能体绑定与安装相互独立。 */
export default function SkillManagerView() {
  const qc = useQueryClient();
  const composingRef = useRef(false);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const [scope, setScope] = useState<{
    type: string; id: string | null; name: string; canImport: boolean; canManage: boolean;
  } | null>(null);
  const [keyword, setKeyword] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [renameModal, setRenameModal] = useState<{ target: SkillFolder; value: string } | null>(null);
  const [viewFile, setViewFile] = useState<SkillFile | null>(null);
  const [confirm, setConfirm] = useState<ConfirmTarget | null>(null);

  // 左栏 scope 链（与知识库同源，资源无关）
  const { data: kbNodes, isLoading: nodesLoading } = useQuery({
    queryKey: ['skill-scopes'], queryFn: () => terminal.skillScopes(),
  });
  const treeData = useMemo(() => buildTree(kbNodes ?? []), [kbNodes]);

  // 默认选中个人节点
  useEffect(() => {
    if (scope || !kbNodes?.length) return;
    const userNode = kbNodes.find((n) => n.scope_type === 'user');
    if (userNode) setScope({
      type: userNode.scope_type, id: userNode.scope_id, name: userNode.name,
      canImport: userNode.can_import, canManage: userNode.can_manage,
    });
  }, [kbNodes, scope]);

  // 右栏：选中 scope 下的技能
  const { data: skills, isLoading: skillsLoading } = useQuery({
    queryKey: ['terminal-skills', scope?.type, scope?.id],
    queryFn: () => terminal.listSkills({ scope_type: scope!.type, scope_id: scope!.id }),
    enabled: !!scope,
  });

  // 展开技能的文件清单
  const { data: expandedFiles } = useQuery({
    queryKey: ['terminal-skill-files', expanded],
    queryFn: () => expanded ? terminal.listSkillFiles(expanded) : Promise.resolve([]),
    enabled: !!expanded,
  });
  const { data: expandedVersions } = useQuery({
    queryKey: ['terminal-skill-versions', expanded],
    queryFn: () => expanded ? terminal.listSkillVersions(expanded) : Promise.resolve([]),
    enabled: !!expanded,
    refetchInterval: (query) => query.state.data?.some((v) => ['pending', 'installing'].includes(v.install_status)) ? 1500 : false,
  });

  // 切换 scope 时收起展开
  useEffect(() => { setExpanded(null); }, [scope?.type, scope?.id]);

  // 导入技能包：ZIP 可包含 SKILL.md、脚本、依赖和资源；MD 继续兼容说明型技能。
  const importSkill = useMutation({
    mutationFn: (payload: { kind: 'archive'; file: File } | { kind: 'folder'; files: File[] }) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      const target = { scope_type: scope.type, scope_id: scope.id };
      return payload.kind === 'archive'
        ? terminal.importSkill(payload.file, target)
        : terminal.importSkillFolder(payload.files, target);
    },
    onSuccess: ({ version }) => {
      qc.invalidateQueries({ queryKey: ['terminal-skills'] });
      qc.invalidateQueries({ queryKey: ['terminal-skill-versions'] });
      message.success(version.install_status === 'ready' ? '技能已安装，可在智能体中绑定' : '技能包已上传，正在安装依赖');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '导入失败'),
  });

  const retryVersion = useMutation({
    mutationFn: (id: string) => terminal.retrySkillVersion(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['terminal-skill-versions'] }); message.success('已重新开始安装'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重试失败'),
  });

  const activateVersion = useMutation({
    mutationFn: (id: string) => terminal.activateSkillVersion(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['terminal-skills'] });
      qc.invalidateQueries({ queryKey: ['terminal-skill-versions'] });
      message.success('已切换活动版本');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '切换失败'),
  });

  // 补传文件
  const uploadFile = useMutation({
    mutationFn: (v: { folderId: string; path: string; content: string }) =>
      terminal.upsertSkillFile(v.folderId, { path: v.path, content: v.content }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['terminal-skill-files'] }); message.success('文件已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const renameSkill = useMutation({
    mutationFn: (v: { id: string; name: string }) => terminal.updateSkill(v.id, { name: v.name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['terminal-skills'] }); setRenameModal(null); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });

  const toggleSkill = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) => terminal.updateSkill(v.id, { is_active: v.is_active }),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ['terminal-skills'] });
      message.success(v.is_active ? '技能已启用' : '技能已停用');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '状态更新失败'),
  });

  const delSkill = useMutation({
    mutationFn: (id: string) => terminal.deleteSkill(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['terminal-skills'] });
      if (expanded) setExpanded(null);
      message.success('已删除');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  const delFile = useMutation({
    mutationFn: (id: string) => terminal.deleteSkillFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['terminal-skill-files'] }); message.success('已删除'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  const openView = (f: SkillFileMeta) => {
    terminal.getSkillFile(f.id).then(setViewFile).catch(() => message.error('读取失败'));
  };

  const kw = keyword.trim().toLowerCase();
  const filtered = kw ? (skills ?? []).filter((s) => s.name.toLowerCase().includes(kw) || s.slug.toLowerCase().includes(kw)) : (skills ?? []);

  const confirmLoading = confirm?.kind === 'skill' ? delSkill.isPending : confirm?.kind === 'file' ? delFile.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'skill') delSkill.mutate(confirm.id);
    else delFile.mutate(confirm.id);
    setConfirm(null);
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <ThunderboltOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>技能</span>
        <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>
          {scope ? `${scope.name} · ${SCOPE_LABEL[scope.type]}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 2:8 两栏主体 */}
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
              onSelect={(node) => setScope({
                type: node.scope, id: node.scopeId, name: node.name,
                canImport: node.canImport, canManage: node.canManage,
              })}
            />
          )}
        </aside>

        {/* 右栏：技能操作区 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!scope ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请从左侧选择作用域节点" />
            </div>
          ) : (
            <>
              {/* 工具条：搜索 + 导入 */}
              <div style={toolbarStyle}>
                <Input
                  allowClear size="small" placeholder="搜索技能"
                  prefix={<SearchOutlined style={{ color: '#9ca3af' }} />}
                  style={{ width: 220 }} value={keyword} onChange={(e) => setKeyword(e.target.value)}
                />
                <input
                  ref={folderInputRef} type="file" multiple
                  {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
                  style={{ display: 'none' }}
                  onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    if (files.length) importSkill.mutate({ kind: 'folder', files });
                    event.target.value = '';
                  }}
                />
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <button
                    style={toolBtnStyle}
                    disabled={!scope.canImport || importSkill.isPending}
                    onClick={() => folderInputRef.current?.click()}
                    title={scope.canImport ? '选择包含唯一 SKILL.md 的文件夹' : '你没有该节点的技能管理权限'}
                  >
                    <FolderOutlined style={{ fontSize: 13 }} /> 选择 Skill 文件夹
                  </button>
                  <Upload
                    showUploadList={false} accept=".zip,.md,.markdown"
                    beforeUpload={(file) => {
                      importSkill.mutate({ kind: 'archive', file: file as File });
                      return false;
                    }}
                  >
                    <button
                      style={{ ...toolBtnStyle, background: scope.canImport ? WB.primary : '#eef0f3', color: scope.canImport ? '#fff' : '#86868b', border: 'none' }}
                      disabled={!scope.canImport || importSkill.isPending}
                      title={scope.canImport ? '上传 Skill ZIP 或单独 SKILL.md' : '你没有该节点的技能管理权限'}
                    >
                      <UploadOutlined style={{ fontSize: 13 }} /> {importSkill.isPending ? '导入中…' : '上传 ZIP/MD'}
                    </button>
                  </Upload>
                </div>
              </div>

              {/* 技能列表（行内展开文件） */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '6px 8px' }} className="wb-scroll-hide">
                {skillsLoading ? (
                  <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
                ) : filtered.length === 0 ? (
                  <PaneEmpty text={kw ? '无匹配技能' : '该作用域下暂无技能，点「导入技能」新建'} />
                ) : (
                  filtered.map((s) => {
                    const owner = scope.canManage;
                    const open = expanded === s.id;
                    return (
                      <div key={s.id} style={{ borderBottom: `1px solid ${WB.border}` }}>
                        <div
                          onClick={() => setExpanded(open ? null : s.id)}
                          style={skillRowStyle(open)}
                        >
                          {open ? <DownOutlined style={{ fontSize: 10, color: '#86868b' }} /> : <RightOutlined style={{ fontSize: 10, color: '#86868b' }} />}
                          <FolderOutlined style={{ fontSize: 16, color: WB.macFolder }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <Typography.Text ellipsis style={{ fontSize: 13, color: '#1d1d1f', fontWeight: 500 }}>{s.name}</Typography.Text>
                              {owner && <span style={minePillStyle}>可管理</span>}
                            </div>
                            <Typography.Text type="secondary" ellipsis style={{ fontSize: 11, display: 'block' }}>{s.slug}</Typography.Text>
                          </div>
                          <div style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                            <IconAction
                              title={owner ? '重命名' : '仅可重命名自己创建的'} disabled={!owner}
                              icon={<EditOutlined />} onClick={() => setRenameModal({ target: s, value: s.name })}
                            />
                            <button
                              style={toolBtnStyle} disabled={!owner || toggleSkill.isPending}
                              onClick={() => toggleSkill.mutate({ id: s.id, is_active: !s.is_active })}
                            >{s.is_active ? '停用' : '启用'}</button>
                            <IconAction
                              title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner}
                              icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'skill', id: s.id, title: s.name })}
                            />
                          </div>
                        </div>

                        {open && (
                          <div style={{ background: '#fafafa', padding: '8px 12px 10px 30px' }}>
                            {(expandedVersions ?? []).map((version) => (
                              <div key={version.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', fontSize: 12 }}>
                                <Tag color={version.install_status === 'ready' ? 'green' : version.install_status === 'failed' ? 'red' : 'blue'}>
                                  v{version.version_no} · {version.install_status}
                                </Tag>
                                <span>
                                  {version.package_format === 'agent_skill' ? 'Agent Skill' : version.runtime}
                                  {version.script_languages?.length ? ` · ${version.script_languages.join('/')}` : ''}
                                  {version.is_executable ? ' · 可执行' : ' · 说明型'}
                                </span>
                                {s.active_version_id === version.id && <Tag color="purple">当前版本</Tag>}
                                <span style={{ flex: 1 }} />
                                {owner && version.install_status === 'failed' && (
                                  <button style={toolBtnStyle} onClick={() => retryVersion.mutate(version.id)}>重试安装</button>
                                )}
                                {owner && version.install_status === 'ready' && s.active_version_id !== version.id && (
                                  <button style={toolBtnStyle} onClick={() => activateVersion.mutate(version.id)}>切换到此版本</button>
                                )}
                                {version.install_error && <Tooltip title={version.install_error}><Tag color="red">查看错误</Tag></Tooltip>}
                                {!!version.compatibility_warnings?.length && (
                                  <Tooltip title={version.compatibility_warnings.join('；')}><Tag color="orange">部分兼容</Tag></Tooltip>
                                )}
                              </div>
                            ))}
                            {!s.active_version_id && <Space style={{ marginBottom: 6 }}>
                              <Upload showUploadList={false}
                                beforeUpload={(file) => {
                                  const reader = new FileReader();
                                  reader.onload = () => uploadFile.mutate({
                                    folderId: s.id, path: file.name, content: String(reader.result ?? ''),
                                  });
                                  reader.onerror = () => message.error('读取文件失败');
                                  reader.readAsText(file);
                                  return false;
                                }}
                              >
                                <button style={toolBtnStyle} disabled={!owner || uploadFile.isPending}>
                                  <UploadOutlined style={{ fontSize: 12 }} /> 补传文件
                                </button>
                              </Upload>
                              {!owner && (
                                <Typography.Text type="secondary" style={{ fontSize: 11 }}>仅可在自己创建的技能下补传 / 删除文件</Typography.Text>
                              )}
                            </Space>}
                            {s.active_version_id && (
                              <Typography.Text type="secondary" style={{ fontSize: 11 }}>版本包文件不可直接修改；请导入新 ZIP/MD 进行升级</Typography.Text>
                            )}
                            {(expandedFiles?.length ?? 0) === 0 ? (
                              <PaneEmpty text="暂无文件（skill.md 定义函数 manifest）" />
                            ) : (
                              (expandedFiles ?? []).map((fl) => (
                                <div key={fl.id} style={fileRowStyle}>
                                  <FileTextOutlined style={{ fontSize: 15, color: WB.macFile }} />
                                  <Typography.Text ellipsis style={{ flex: 1, fontSize: 13 }}>{leaf(fl.path)}</Typography.Text>
                                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>{fl.size} B</Typography.Text>
                                  <div style={{ display: 'flex', gap: 2 }} onClick={(e) => e.stopPropagation()}>
                                    <IconAction title="查看" icon={<EyeOutlined />} onClick={() => openView(fl)} />
                                    <IconAction
                                      title={s.active_version_id ? '版本包文件不可直接删除' : owner ? '删除' : '无管理权限'}
                                      danger disabled={!owner || !!s.active_version_id}
                                      icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'file', id: fl.id, title: leaf(fl.path) })}
                                    />
                                  </div>
                                </div>
                              ))
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 重命名技能 */}
      {renameModal && (
        <ModalBox
          title="重命名技能" okText="保存" loading={renameSkill.isPending}
          onCancel={() => setRenameModal(null)}
          onOk={() => {
            const name = renameModal.value.trim();
            if (!name) { message.warning('请输入名称'); return; }
            renameSkill.mutate({ id: renameModal.target.id, name });
          }}
        >
          <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>名称</Typography.Text>
          <Input
            autoFocus
            placeholder="技能名称"
            value={renameModal.value}
            onChange={(e) => setRenameModal({ ...renameModal, value: e.target.value })}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setRenameModal({ ...renameModal, value: (e.target as HTMLInputElement).value }); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              const name = renameModal.value.trim();
              if (name) renameSkill.mutate({ id: renameModal.target.id, name });
            }}
            style={{ fontSize: 13, marginTop: 4 }}
          />
        </ModalBox>
      )}

      {/* 查看文件 */}
      {viewFile && (
        <ModalBox
          title={leaf(viewFile.path)} width={720} okText="关闭" okDanger={false}
          onCancel={() => setViewFile(null)}
          onOk={() => setViewFile(null)}
        >
          <div className="wb-md" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 4 }}>
            {/\.md$/i.test(viewFile.path) || !viewFile.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{viewFile.content ?? ''}</ReactMarkdown>
            ) : (
              <pre className="wb-pre" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12, background: '#f5f5f5', padding: 8 }}>{viewFile.content}</pre>
            )}
          </div>
        </ModalBox>
      )}

      {/* 删除确认 */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === 'skill' ? '删除该技能？' : '删除该文件？'}
        desc={confirm?.kind === 'skill' ? `将删除技能「${confirm?.title}」及其全部文件，此操作不可撤销。` : undefined}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />
    </div>
  );
}

// ── MacOS 风格作用域树 ──────────────────────────────────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (node: TreeNode) => void;
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
          onClick={() => onSelect(node)}
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

// ── 通用模态框（MacOS 风格，标题 + 自定义内容 + 取消/确定） ─────────────

function ModalBox(props: {
  title: string; width?: number; okText?: string; okDanger?: boolean; loading?: boolean;
  onCancel: () => void; onOk: () => void; children: ReactNode;
}) {
  const { title, width = 400, okText = '确定', okDanger = true, loading, onCancel, onOk, children } = props;
  return (
    <div style={modalOverlayStyle} onClick={onCancel}>
      <div style={{ ...modalCardStyle, width }} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>{title}</div>
        <div style={{ padding: '18px' }}>{children}</div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={onCancel}>取消</button>
          <button
            style={{ ...toolBtnStyle, background: okDanger ? '#ff3b30' : WB.primary, color: '#fff', border: 'none' }}
            disabled={loading} onClick={onOk}
          >
            {loading ? `${okText}中…` : okText}
          </button>
        </div>
      </div>
    </div>
  );
}

function PaneEmpty({ text }: { text: string }) {
  return <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 32 }}>{text}</div>;
}

function IconAction(props: { title: string; icon: ReactNode; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  const { title, icon, onClick, danger, disabled } = props;
  return (
    <Tooltip title={title}>
      <button style={iconActionBtnStyle(danger, disabled)} disabled={disabled} onClick={onClick}>{icon}</button>
    </Tooltip>
  );
}

// Space 简用：antd Space 在终端视图里偶尔引入额外样式，这里直接内联 flex 容器
function Space({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return <div style={{ display: 'flex', alignItems: 'center', gap: 8, ...(style ?? {}) }}>{children}</div>;
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

const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8, flexWrap: 'wrap',
  background: '#fbfbfd',
};

const skillRowStyle = (open: boolean): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
  cursor: 'pointer', fontSize: 13,
  background: open ? '#f0f1f4' : 'transparent',
});

const minePillStyle: CSSProperties = {
  fontSize: 10, color: WB.primary, background: `${WB.primary}1A`,
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const fileRowStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6,
  fontSize: 13,
};

const toolBtnStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 12, color: '#1d1d1f',
  background: '#eef0f3', border: 'none', cursor: 'pointer', padding: '5px 10px', borderRadius: 6,
  height: 28,
};

const iconActionBtnStyle = (danger?: boolean, disabled?: boolean): CSSProperties => ({
  width: 24, height: 24, borderRadius: 6, border: 'none',
  cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12,
  background: 'transparent',
  color: disabled ? '#d1d5db' : (danger ? '#ff3b30' : '#1d1d1f'),
});

const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const modalCardStyle: CSSProperties = {
  maxWidth: 'calc(100vw - 32px)', background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
