import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Input, Modal, Tooltip, Typography, Upload, message, Tag,
} from 'antd';
import {
  DeleteOutlined, EditOutlined, SearchOutlined, UploadOutlined,
  FolderOutlined, FileTextOutlined, EyeOutlined, DownOutlined, RightOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined, ToolOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { skillStore } from '../../api/client';
import type { SkillFile, SkillFileMeta, SkillFolder } from '../../api/client';
import { ApiError } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { useOrgTree } from '../../hooks/useOrgTree';
import {
  FinderShell, TitleBar, Sidebar, MacTree, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, FS } from '../../components/finder/theme';

interface ScopeState {
  scope_type: 'organization' | 'department' | 'team' | 'user';
  scope_id: string | null;
  orgId: string;
  nodeName: string;
}

const SCOPE_PREFIX: Record<ScopeState['scope_type'], string> = {
  organization: 'org', department: 'dept', team: 'team', user: 'user',
};
const NODE_ICON: Record<string, ReactNode> = {
  org: <BankOutlined />, dept: <ApartmentOutlined />, team: <TeamOutlined />, user: <UserOutlined />,
};
const iconForKey = (key: string): ReactNode => NODE_ICON[key.split(':')[0]] ?? <FolderOutlined />;

/** 技能（文件夹）管理：Finder 风。左：组织架构树（节点作用域）；右：技能列表（可展开看文件）。
 *  标准 Agent Skill 可通过文件夹或 ZIP 安装；旧版 Markdown/连接器 Skill 继续兼容。 */
export default function Skills() {
  const qc = useQueryClient();
  const folderInputRef = useRef<HTMLInputElement>(null);
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();
  const [orgId, setOrgId] = useState<string | undefined>();

  const [scope, setScope] = useState<ScopeState | null>(null);
  const [keyword, setKeyword] = useState('');
  const [expanded, setExpanded] = useState<string | null>(null);
  const [renameModal, setRenameModal] = useState<SkillFolder | null>(null);
  const [renameName, setRenameName] = useState('');
  const [viewFile, setViewFile] = useState<SkillFile | null>(null);
  const [confirm, setConfirm] = useState<{ kind: 'folder' | 'file'; id: string; name: string } | null>(null);

  const treeDataScoped = useMemo(() => {
    if (!orgId) return [];
    return treeData.filter((n) => n.key === `org:${orgId}`);
  }, [treeData, orgId]);

  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({
        key: n.key, label: n.title, icon: iconForKey(n.key),
        children: n.children?.length ? build(n.children) : undefined,
      }));
    return build(treeDataScoped);
  }, [treeDataScoped]);

  // 选中组织变化（或树首次加载且未选 scope）→ 落到该组织根节点作为默认作用域
  useEffect(() => {
    if (scope || treeLoading || !orgId) return;
    const info = nodeMap.get(`org:${orgId}`);
    if (info) setScope({ scope_type: 'organization', scope_id: null, orgId: info.orgId, nodeName: info.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, treeLoading, treeData]);

  const scopeRef = scope ? { scope_type: scope.scope_type, scope_id: scope.scope_id } : null;
  const selectedKey = scope ? `${SCOPE_PREFIX[scope.scope_type]}:${scope.scope_id ?? scope.orgId}` : null;

  const { data: folders, isLoading: foldersLoading } = useQuery({
    queryKey: ['skill-folders', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => scope ? skillStore.listFolders(scope.orgId, scopeRef!) : Promise.resolve([]),
    enabled: !!scope,
  });

  const { data: expandedFiles } = useQuery({
    queryKey: ['skill-files', expanded],
    queryFn: () => expanded ? skillStore.listFiles(expanded) : Promise.resolve([]),
    enabled: !!expanded,
  });
  const { data: expandedVersions } = useQuery({
    queryKey: ['skill-versions', expanded],
    queryFn: () => expanded ? skillStore.listVersions(expanded) : Promise.resolve([]),
    enabled: !!expanded,
    refetchInterval: (query) => query.state.data?.some((v) => ['pending', 'installing'].includes(v.install_status)) ? 1500 : false,
  });

  const uploadSkill = useMutation({
    mutationFn: (payload: { kind: 'archive'; file: File } | { kind: 'folder'; files: File[] }) => {
      if (!scope) return Promise.reject(new Error('no scope'));
      const target = { scope_type: scope.scope_type, scope_id: scope.scope_id };
      return payload.kind === 'archive'
        ? skillStore.importPackage(scope.orgId, payload.file, target)
        : skillStore.importPackageFolder(scope.orgId, payload.files, target);
    },
    onSuccess: ({ version }) => {
      qc.invalidateQueries({ queryKey: ['skill-folders'] });
      qc.invalidateQueries({ queryKey: ['skill-versions'] });
      message.success(version.install_status === 'ready' ? '技能已安装' : '技能包已上传，正在安装依赖');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const uploadFile = useMutation({
    mutationFn: (v: { folderId: string; path: string; content: string }) =>
      skillStore.upsertFile(v.folderId, { path: v.path, content: v.content }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-files'] }); message.success('文件已上传'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '上传失败'),
  });

  const retryVersion = useMutation({
    mutationFn: (id: string) => skillStore.retryVersion(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-versions'] }); message.success('已重新开始安装'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重试失败'),
  });

  const activateVersion = useMutation({
    mutationFn: (id: string) => skillStore.activateVersion(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['skill-folders'] });
      qc.invalidateQueries({ queryKey: ['skill-versions'] });
      message.success('已切换活动版本');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '切换失败'),
  });

  const delFolder = useMutation({
    mutationFn: (id: string) => skillStore.deleteFolder(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-folders'] }); if (expanded) setExpanded(null); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  const delFile = useMutation({
    mutationFn: (id: string) => skillStore.deleteFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-files'] }); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  const renameFolder = useMutation({
    mutationFn: (v: { id: string; name: string }) => skillStore.updateFolder(v.id, { name: v.name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['skill-folders'] }); setRenameModal(null); message.success('已重命名'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重命名失败'),
  });

  const toggleFolder = useMutation({
    mutationFn: (v: { id: string; is_active: boolean }) => skillStore.updateFolder(v.id, { is_active: v.is_active }),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ['skill-folders'] });
      message.success(v.is_active ? '技能已启用' : '技能已停用');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '状态更新失败'),
  });

  const openView = (f: SkillFileMeta) => {
    skillStore.getFile(f.id).then(setViewFile).catch(() => message.error('读取失败'));
  };

  const kw = keyword.trim().toLowerCase();
  const filtered = kw ? (folders ?? []).filter((f) => f.name.toLowerCase().includes(kw) || f.slug.toLowerCase().includes(kw)) : (folders ?? []);

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<ToolOutlined />}
        title="技能"
        titleExtra={<OrgSelect value={orgId} onChange={(v) => { setOrgId(v); setExpanded(null); setViewFile(null); setScope(null); }} />}
        extra={
          <>
            <Input size="small" allowClear placeholder="搜索技能" prefix={<SearchOutlined style={{ color: WB.textAux }} />} style={{ width: 180 }} value={keyword} onChange={(e) => setKeyword(e.target.value)} />
            <input
              ref={folderInputRef} type="file" multiple
              {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
              style={{ display: 'none' }}
              onChange={(event) => {
                const files = Array.from(event.target.files ?? []);
                if (files.length) uploadSkill.mutate({ kind: 'folder', files });
                event.target.value = '';
              }}
            />
            <ToolButton
              icon={<FolderOutlined style={{ fontSize: 13 }} />}
              disabled={uploadSkill.isPending || !scope}
              onClick={() => folderInputRef.current?.click()}
            >选择 Skill 文件夹</ToolButton>
            <Upload showUploadList={false} accept=".zip,.md,.markdown"
              beforeUpload={(file) => {
                uploadSkill.mutate({ kind: 'archive', file: file as File });
                return false;
              }}
            >
              <ToolButton primary icon={<UploadOutlined style={{ fontSize: 13 }} />} disabled={uploadSkill.isPending}>上传 ZIP</ToolButton>
            </Upload>
          </>
        }
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
                setExpanded(null);
                setScope({ scope_type: info.type, scope_id: info.type === 'organization' ? null : info.id, orgId: info.orgId, nodeName: info.name });
              }}
            />
          )}
        </Sidebar>

        {/* 右栏：技能列表（可展开看文件） */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!scope ? (
            <FinderEmpty description="请从左侧选择节点" />
          ) : (
            <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
              {foldersLoading ? <FinderLoading /> : filtered.length === 0 ? (
                <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>
                  {kw ? '无匹配技能' : '该节点下暂无技能，点「上传技能」新建'}
                </div>
              ) : filtered.map((f) => {
                const open = expanded === f.id;
                return (
                  <div key={f.id}>
                    <div
                      onClick={() => setExpanded(open ? null : f.id)}
                      onMouseEnter={(e) => { e.currentTarget.style.background = open ? WB.hover : WB.hover; }}
                      onMouseLeave={(e) => { e.currentTarget.style.background = open ? '#f5f5f7' : 'transparent'; }}
                      style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6, cursor: 'pointer', fontSize: FS.body, lineHeight: 1, background: open ? '#f5f5f7' : 'transparent' }}
                    >
                      {open ? <DownOutlined style={{ fontSize: 11, color: WB.textAux }} /> : <RightOutlined style={{ fontSize: 11, color: WB.textAux }} />}
                      <FolderOutlined style={{ fontSize: 16, color: '#faad14' }} />
                      <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{f.name}</span>
                      <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                        <Tooltip title="重命名"><ActionBtn icon={<EditOutlined />} onClick={() => { setRenameModal(f); setRenameName(f.name); }} /></Tooltip>
                        <ToolButton onClick={() => toggleFolder.mutate({ id: f.id, is_active: !f.is_active })}>{f.is_active ? '停用' : '启用'}</ToolButton>
                        <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'folder', id: f.id, name: f.name })} />
                      </span>
                    </div>
                    {open && (
                      <div style={{ padding: '4px 12px 10px 40px', borderBottom: `1px solid ${WB.border}` }}>
                        {(expandedVersions ?? []).map((version) => (
                          <div key={version.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '5px 0', fontSize: FS.micro }}>
                            <Tag color={version.install_status === 'ready' ? 'green' : version.install_status === 'failed' ? 'red' : 'blue'}>
                              v{version.version_no} · {version.install_status}
                            </Tag>
                            <span>
                              {version.package_format === 'agent_skill' ? 'Agent Skill' : version.runtime}
                              {version.script_languages?.length ? ` · ${version.script_languages.join('/')}` : ''}
                              {version.is_executable ? ' · 可执行' : ' · 说明型'}
                            </span>
                            {f.active_version_id === version.id && <Tag color="purple">当前版本</Tag>}
                            <span style={{ flex: 1 }} />
                            {version.install_status === 'failed' && (
                              <ToolButton onClick={() => retryVersion.mutate(version.id)}>重试安装</ToolButton>
                            )}
                            {version.install_status === 'ready' && f.active_version_id !== version.id && (
                              <ToolButton onClick={() => activateVersion.mutate(version.id)}>切换版本</ToolButton>
                            )}
                            {version.install_error && <Tooltip title={version.install_error}><Tag color="red">查看错误</Tag></Tooltip>}
                            {!!version.compatibility_warnings?.length && (
                              <Tooltip title={version.compatibility_warnings.join('；')}><Tag color="orange">部分兼容</Tag></Tooltip>
                            )}
                          </div>
                        ))}
                        {!f.active_version_id && <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                          <Upload showUploadList={false}
                            beforeUpload={(file) => {
                              const reader = new FileReader();
                              reader.onload = () => {
                                uploadFile.mutate({ folderId: f.id, path: file.name, content: String(reader.result ?? '') });
                              };
                              reader.onerror = () => message.error('读取文件失败');
                              reader.readAsText(file);
                              return false;
                            }}
                          >
                            <ToolButton icon={<UploadOutlined style={{ fontSize: 12 }} />} disabled={uploadFile.isPending}>上传文件</ToolButton>
                          </Upload>
                          <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>skill.md 定义函数 manifest</Typography.Text>
                        </div>}
                        {f.active_version_id && (
                          <Typography.Text style={{ fontSize: FS.micro, color: WB.textAux }}>版本包文件不可直接修改；请导入新 ZIP/MD 进行升级</Typography.Text>
                        )}
                        {(expandedFiles?.length ?? 0) === 0 ? (
                          <div style={{ padding: '4px 0', color: WB.textAux, fontSize: FS.micro }}>暂无文件</div>
                        ) : (expandedFiles ?? []).map((fl) => (
                          <div key={fl.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 0', fontSize: FS.body }}>
                            <FileTextOutlined style={{ fontSize: 14, color: '#8c8c8c' }} />
                            <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{fl.path}</span>
                            <span style={{ fontSize: FS.micro, color: WB.textAux }}>{fl.size} B</span>
                            <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }}>
                              <Tooltip title="查看"><ActionBtn icon={<EyeOutlined />} onClick={() => openView(fl)} /></Tooltip>
                              <ActionBtn
                                icon={<DeleteOutlined />} danger
                                title={f.active_version_id ? '版本包文件不可直接删除' : '删除'}
                                onClick={f.active_version_id ? undefined : () => setConfirm({ kind: 'file', id: fl.id, name: fl.path })}
                              />
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* 重命名技能 */}
      <Modal title="重命名技能" open={!!renameModal}
        onCancel={() => setRenameModal(null)}
        onOk={() => {
          const name = renameName.trim();
          if (!name) { message.warning('请输入名称'); return; }
          if (renameModal) renameFolder.mutate({ id: renameModal.id, name });
        }}
        confirmLoading={renameFolder.isPending}>
        <Input value={renameName} onChange={(e) => setRenameName(e.target.value)} placeholder="技能名称" />
      </Modal>

      {/* 查看文件 */}
      <Modal title={viewFile?.path ?? ''} open={!!viewFile}
        onCancel={() => setViewFile(null)} footer={null} width={720}>
        {viewFile && (
          <div className="wb-md" style={{ maxHeight: '60vh', overflowY: 'auto', padding: 8 }}>
            {/\.md$/i.test(viewFile.path) || !viewFile.content ? (
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{viewFile.content ?? ''}</ReactMarkdown>
            ) : (
              <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 12, background: '#f5f5f5', padding: 8 }}>{viewFile.content}</pre>
            )}
          </div>
        )}
      </Modal>

      <ConfirmModal
        open={!!confirm}
        title={confirm?.kind === 'folder' ? '删除技能' : '删除文件'}
        desc={confirm?.kind === 'folder'
          ? `将删除技能「${confirm?.name}」及其全部文件，此操作不可撤销。`
          : `确定删除文件「${confirm?.name}」？此操作不可撤销。`}
        loading={confirm?.kind === 'folder' ? delFolder.isPending : delFile.isPending}
        onCancel={() => setConfirm(null)}
        onOk={() => {
          if (!confirm) return;
          if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
          else delFile.mutate(confirm.id);
          setConfirm(null);
        }}
      />
    </FinderShell>
  );
}

/** 紧凑行内动作按钮（图标按钮）。 */
function ActionBtn({ icon, danger, onClick, title }: {
  icon: ReactNode; danger?: boolean; onClick?: () => void; title?: string;
}) {
  return (
    <Tooltip title={title}>
      <button
        onClick={onClick}
        style={{
          width: 24, height: 24, borderRadius: 5, border: 'none', cursor: 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
          background: 'transparent', color: danger ? WB.danger : WB.textAux,
        }}
      >
        {icon}
      </button>
    </Tooltip>
  );
}
