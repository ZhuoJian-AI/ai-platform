import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Input, Typography, message, Empty, Spin, Tooltip, Upload, Progress } from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  FolderOutlined, FileTextOutlined, FolderAddOutlined, ArrowUpOutlined,
  HomeOutlined, PlusOutlined, EditOutlined, RightOutlined, TagsOutlined,
  InboxOutlined, FolderOpenOutlined, CheckCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, UploadOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  terminal, type KbNode, type RagCollection, type RagDocument, type RagFolder,
} from '../../api/client';
import { ApiError } from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import ConfirmModal from '../../components/finder/ConfirmModal';
import DocEditDrawer from './DocEditDrawer';

/** WorkBuddy 配色（与 WorkspaceManagerView 一致）。 */
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

/** 取路径末段。 */
function leaf(p: string): string {
  return p.includes('/') ? p.slice(p.lastIndexOf('/') + 1) : p;
}

/** 支持上传的扩展名（与后端 doc_parser 对齐：pdf/docx/xlsx/csv/txt/md/html）。 */
const ACCEPT_EXTS = ['pdf', 'docx', 'xlsx', 'xls', 'xlsm', 'csv', 'tsv', 'txt', 'text', 'log', 'md', 'markdown', 'htm', 'html'];
const ACCEPT_ATTR = ACCEPT_EXTS.map((e) => `.${e}`).join(',');
const isAccepted = (name: string): boolean => {
  const ext = (name.split('.').pop() || '').toLowerCase();
  return ACCEPT_EXTS.includes(ext);
};

/** 文档上传入队后的阶段：等待→上传→解析→分块→嵌入→就绪/失败。 */
type UploadPhase = 'queued' | 'uploading' | 'parsing' | 'chunking' | 'embedding' | 'done' | 'failed';
const PHASE_LABEL: Record<UploadPhase, string> = {
  queued: '等待中', uploading: '上传中', parsing: '解析中',
  chunking: '分块中', embedding: '嵌入中', done: '就绪', failed: '失败',
};
interface UploadItem {
  uid: string;
  file: File;
  phase: UploadPhase;
  percent: number;
  error?: string;
  docId?: string;
  folderPath?: string;
}

type ConfirmTarget =
  | { kind: 'coll'; id: string; title: string }
  | { kind: 'folder'; id: string; title: string }
  | { kind: 'doc'; id: string; title: string };

/** 终端「知识库」视图：左中右三栏。
 *  左栏：用户可见作用域单链（组织/部门/团队/个人）；中栏：选中 scope 下的知识库；
 *  右栏：选中知识库的文件夹与文档。
 *  新建：任意可见 scope 均可；删除/重命名/编辑：仅限「自己创建」的资源（created_by === 当前用户）。 */
export default function KnowledgeBaseView() {
  const qc = useQueryClient();
  const { user } = useUserAuth();
  const myId = user?.id ?? null;
  const composingRef = useRef(false);

  const [scope, setScope] = useState<{ type: string; id: string | null; name: string } | null>(null);
  const [selectedColl, setSelectedColl] = useState<RagCollection | null>(null);
  const [currentFolder, setCurrentFolder] = useState(''); // "" = 根

  // 弹窗：知识库 / 文件夹 / 文档 的新建与重命名
  const [nameModal, setNameModal] = useState<{
    open: boolean; mode: 'create-coll' | 'rename-coll' | 'create-folder' | 'rename-folder' | 'create-doc' | 'rename-doc';
    target?: RagCollection | RagFolder | RagDocument | null;
    value: string; desc?: string;
  }>({ open: false, mode: 'create-coll', value: '', desc: '' });
  const [confirm, setConfirm] = useState<ConfirmTarget | null>(null);
  const [editDoc, setEditDoc] = useState<RagDocument | null>(null);

  // 文档上传弹窗（与管理端一致：文件 + 文件夹，解析入库带进度）
  const [uploadModal, setUploadModal] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<UploadItem[]>([]);
  const queueRef = useRef<UploadItem[]>([]);
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const folderInputRef = useRef<HTMLInputElement>(null);

  const upsert = (uid: string, patch: Partial<UploadItem>) => {
    queueRef.current = queueRef.current.map((it) => (it.uid === uid ? { ...it, ...patch } : it));
    setUploadQueue(queueRef.current);
  };
  const stopPoll = (uid: string) => {
    const t = timersRef.current[uid];
    if (t) { clearTimeout(t); delete timersRef.current[uid]; }
  };
  const pollStatus = (uid: string, docId: string) => {
    stopPoll(uid);
    timersRef.current[uid] = setTimeout(async () => {
      try {
        const s = await terminal.getKbDocStatus(docId);
        const phase: UploadPhase =
          s.status === 'parsing' ? 'parsing'
          : s.status === 'chunking' ? 'chunking'
          : s.status === 'embedding' ? 'embedding'
          : s.status === 'ready' ? 'done'
          : s.status === 'failed' ? 'failed' : 'embedding';
        upsert(uid, { phase, percent: s.progress });
        if (s.status === 'ready') { stopPoll(uid); startNext(); }
        else if (s.status === 'failed') { stopPoll(uid); upsert(uid, { error: s.parse_error ?? '入库失败' }); startNext(); }
        else pollStatus(uid, docId);
      } catch {
        timersRef.current[uid] = setTimeout(() => pollStatus(uid, docId), 1500);
      }
    }, 1200);
  };
  const processOne = async (item: UploadItem) => {
    try {
      const doc = await terminal.uploadKbDocumentFile(
        selectedColl!.id, item.file, { folder_path: item.folderPath ?? currentFolder },
        (ratio) => upsert(item.uid, { phase: 'uploading', percent: Math.round(ratio * 100) }),
      );
      upsert(item.uid, { docId: doc.id, phase: 'parsing', percent: doc.progress || 5 });
      pollStatus(item.uid, doc.id);
    } catch (e: unknown) {
      upsert(item.uid, { phase: 'failed', error: e instanceof ApiError ? e.message : '上传失败' });
      startNext();
    }
  };
  const startNext = () => {
    const inFlight = queueRef.current.some((it) =>
      it.phase === 'uploading' || it.phase === 'parsing' || it.phase === 'chunking' || it.phase === 'embedding');
    if (inFlight) return;
    const next = queueRef.current.find((it) => it.phase === 'queued');
    if (!next) {
      if (queueRef.current.length && queueRef.current.every((it) => it.phase === 'done' || it.phase === 'failed')) {
        qc.invalidateQueries({ queryKey: ['kb-docs'] });
      }
      return;
    }
    upsert(next.uid, { phase: 'uploading', percent: 0 });
    void processOne(next);
  };
  const enqueue = (items: UploadItem[]) => {
    if (!items.length) return;
    queueRef.current = [...queueRef.current, ...items];
    setUploadQueue(queueRef.current);
    startNext();
  };
  const handleFiles = (files: File[]) => {
    enqueue(files.map((f) => ({
      uid: `${f.name}-${f.size}-${f.lastModified}-${Math.random().toString(36).slice(2, 6)}`,
      file: f, phase: 'queued' as UploadPhase, percent: 0, folderPath: currentFolder,
    })));
  };
  /** 文件夹上传：按 webkitRelativePath 还原子目录并入当前 folder_path。 */
  const handleFolder = (fileList: FileList | null) => {
    if (!fileList || !fileList.length) return;
    const items: UploadItem[] = [];
    let skipped = 0;
    Array.from(fileList).forEach((f) => {
      if (!isAccepted(f.name)) { skipped += 1; return; }
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      const slash = rel.lastIndexOf('/');
      const subDir = slash >= 0 ? rel.slice(0, slash) : '';
      const folderPath = subDir ? (currentFolder ? `${currentFolder}/${subDir}` : subDir) : currentFolder;
      items.push({
        uid: `${rel}-${f.size}-${Math.random().toString(36).slice(2, 6)}`,
        file: f, phase: 'queued' as UploadPhase, percent: 0, folderPath,
      });
    });
    if (skipped > 0) message.info(`已跳过 ${skipped} 个不支持的文件（仅支持 pdf/docx/xlsx/csv/txt/md/html）`);
    enqueue(items);
  };
  const closeUploadModal = () => {
    Object.keys(timersRef.current).forEach(stopPoll);
    setUploadModal(false);
  };
  const openUpload = () => { setUploadQueue([]); queueRef.current = []; setUploadModal(true); };
  // 卸载时清理轮询定时器
  useEffect(() => () => { Object.keys(timersRef.current).forEach(stopPoll); }, []);

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

  // 中栏：选中 scope 下的知识库
  const { data: collections, isLoading: collLoading } = useQuery({
    queryKey: ['kb-collections', scope?.type, scope?.id],
    queryFn: () => terminal.listKbCollections({ scope_type: scope!.type, scope_id: scope!.id }),
    enabled: !!scope,
  });

  // 右栏：选中知识库 + 当前文件夹
  const { data: folders } = useQuery({
    queryKey: ['kb-folders', selectedColl?.id, currentFolder],
    queryFn: () => terminal.listKbFolders(selectedColl!.id, currentFolder),
    enabled: !!selectedColl,
  });
  const { data: docs } = useQuery({
    queryKey: ['kb-docs', selectedColl?.id, currentFolder],
    queryFn: () => terminal.listKbDocuments(selectedColl!.id, currentFolder),
    enabled: !!selectedColl,
  });

  // 切换知识库回到根目录
  useEffect(() => { setCurrentFolder(''); }, [selectedColl?.id]);

  const isOwner = (created_by: string | null) => !!myId && created_by === myId;

  // ── 集合 增/改/删 ──
  const saveColl = useMutation({
    mutationFn: () => {
      const m = nameModal;
      const name = m.value.trim();
      if (!name) return Promise.reject(new Error('请输入名称'));
      if (m.mode === 'rename-coll' && m.target) {
        return terminal.updateKbCollection((m.target as RagCollection).id, { name, description: m.desc ?? null });
      }
      return terminal.createKbCollection({
        name, description: m.desc ?? null,
        chunk_size: 800, chunk_overlap: 100,
        scope_type: scope!.type, scope_id: scope!.id,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-collections'] });
      setNameModal((m) => ({ ...m, open: false }));
      message.success('已保存');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const delColl = useMutation({
    mutationFn: (id: string) => terminal.deleteKbCollection(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-collections'] });
      if (selectedColl) setSelectedColl(null);
      message.success('已删除');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  // ── 文件夹 增/改/删 ──
  const saveFolder = useMutation({
    mutationFn: () => {
      const m = nameModal;
      const name = m.value.trim();
      if (!name || name.includes('/')) return Promise.reject(new Error('请输入有效文件夹名（不含 /）'));
      const path = currentFolder ? `${currentFolder}/${name}` : name;
      if (m.mode === 'rename-folder' && m.target) return terminal.renameKbFolder((m.target as RagFolder).id, path);
      return terminal.createKbFolder(selectedColl!.id, path);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-folders'] });
      qc.invalidateQueries({ queryKey: ['kb-docs'] });
      setNameModal((m) => ({ ...m, open: false }));
      message.success('已保存');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '操作失败'),
  });
  const delFolder = useMutation({
    mutationFn: (id: string) => terminal.deleteKbFolder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-folders'] });
      qc.invalidateQueries({ queryKey: ['kb-docs'] });
      message.success('已删除');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  // ── 文档 增/改/删 ──
  const saveDoc = useMutation({
    mutationFn: () => {
      const m = nameModal;
      const source = m.value.trim();
      if (!source) return Promise.reject(new Error('请输入来源标识'));
      if (m.mode === 'rename-doc' && m.target) {
        return terminal.updateKbDocument((m.target as RagDocument).id, { source, title: m.desc ?? null });
      }
      // create-doc：value=source，desc=title；正文留空，用户在「编辑分块」抽屉中填写后重新入库
      return terminal.ingestKbDocument(selectedColl!.id, {
        source, title: m.desc ?? null, content: '', folder_path: currentFolder,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['kb-docs'] });
      setNameModal((m) => ({ ...m, open: false }));
      message.success('已保存，可点击「编辑」填充分块后入库');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const delDoc = useMutation({
    mutationFn: (id: string) => terminal.deleteKbDocument(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['kb-docs'] });
      setEditDoc((d) => (d && d.id === id ? null : d));
      message.success('已删除');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  const submitNameModal = () => {
    const mode = nameModal.mode;
    if (mode === 'create-coll' || mode === 'rename-coll') saveColl.mutate();
    else if (mode === 'create-folder' || mode === 'rename-folder') saveFolder.mutate();
    else saveDoc.mutate();
  };

  const confirmLoading = confirm?.kind === 'coll' ? delColl.isPending
    : confirm?.kind === 'folder' ? delFolder.isPending
      : confirm?.kind === 'doc' ? delDoc.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'coll') delColl.mutate(confirm.id);
    else if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else delDoc.mutate(confirm.id);
    setConfirm(null);
  };

  const breadcrumb = useMemo(() => {
    const segs = currentFolder ? currentFolder.split('/') : [];
    return (
      <div style={pathBarStyle}>
        <span className="wb-path-seg" onClick={() => setCurrentFolder('')} style={pathSegStyle}>
          <HomeOutlined style={{ fontSize: 12, marginRight: 4 }} />{selectedColl?.name ?? '根'}
        </span>
        {segs.map((seg, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center' }}>
            <RightOutlined style={{ fontSize: 9, color: '#b0b0b5', margin: '0 2px' }} />
            <span className="wb-path-seg" onClick={() => setCurrentFolder(segs.slice(0, i + 1).join('/'))} style={pathSegStyle}>{seg}</span>
          </span>
        ))}
      </div>
    );
  }, [currentFolder, selectedColl]);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <FolderOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>知识库</span>
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
              onSelect={(type, id, name) => { setSelectedColl(null); setScope({ type, id, name }); }}
            />
          )}
        </aside>

        {/* 中栏：知识库列表 */}
        <section style={midPaneStyle}>
          <div style={midToolbarStyle}>
            <span style={{ fontSize: 12, fontWeight: 600, color: '#1d1d1f' }}>
              知识库 {collections?.length ? `(${collections.length})` : ''}
            </span>
            <button
              style={toolBtnStyle} disabled={!scope}
              onClick={() => setNameModal({ open: true, mode: 'create-coll', value: '', desc: '' })}
            >
              <PlusOutlined style={{ fontSize: 13 }} /> 新建
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto' }} className="wb-scroll-hide">
            {!scope ? (
              <PaneEmpty text="请从左侧选择作用域节点" />
            ) : collLoading ? (
              <div style={{ textAlign: 'center', padding: 32 }}><Spin /></div>
            ) : !collections?.length ? (
              <PaneEmpty text="该作用域下暂无知识库" />
            ) : (
              collections.map((c) => {
                const owner = isOwner(c.created_by);
                const active = selectedColl?.id === c.id;
                return (
                  <div
                    key={c.id}
                    onClick={() => setSelectedColl(c)}
                    style={midItemStyle(active)}
                  >
                    <FolderOutlined style={{ fontSize: 16, color: active ? WB.primary : WB.macFolder, flex: '0 0 auto' }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <Typography.Text ellipsis style={{ fontSize: 13, color: active ? WB.primary : '#1d1d1f', fontWeight: active ? 600 : 400 }}>{c.name}</Typography.Text>
                        {owner && <span style={minePillStyle}>我创建</span>}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                      <IconAction
                        title={owner ? '重命名' : '仅可重命名自己创建的'} disabled={!owner}
                        icon={<EditOutlined />} onClick={() => setNameModal({ open: true, mode: 'rename-coll', target: c, value: c.name, desc: c.description ?? '' })}
                      />
                      <IconAction
                        title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner}
                        icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'coll', id: c.id, title: c.name })}
                      />
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* 右栏：文件夹 / 文档 */}
        <section style={{ flex: 7, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff', borderLeft: `1px solid ${WB.border}` }}>
          {!selectedColl ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="请从中栏选择知识库" />
            </div>
          ) : (
            <>
              {/* 工具条 + 面包屑 */}
              <div style={toolbarStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
                  <button
                    style={navBtnStyle(currentFolder === '')}
                    disabled={currentFolder === ''}
                    onClick={() => setCurrentFolder((c) => c.slice(0, c.lastIndexOf('/') >= 0 ? c.lastIndexOf('/') : 0))}
                    title="返回上一级"
                  ><ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} /></button>
                  {breadcrumb}
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button style={toolBtnStyle} onClick={() => setNameModal({ open: true, mode: 'create-folder', value: '' })}>
                    <FolderAddOutlined style={{ fontSize: 13 }} /> 新建文件夹
                  </button>
                  <button
                    style={{ ...toolBtnStyle, background: WB.primary, color: '#fff' }}
                    onClick={openUpload}
                  >
                    <UploadOutlined style={{ fontSize: 13 }} /> 上传文档
                  </button>
                </div>
              </div>

              {/* 列表 */}
              <div style={{ flex: 1, overflowY: 'auto', padding: '8px 12px' }} className="wb-scroll-hide">
                {(!folders?.length && !docs?.length) ? (
                  <PaneEmpty text="此处暂无文件夹 / 文档" />
                ) : (
                  <>
                    {(folders ?? []).map((f) => {
                      const owner = isOwner(f.created_by);
                      return (
                        <div key={f.id} style={rowStyle(false)} onClick={() => setCurrentFolder(f.path)}>
                          <FolderOutlined style={{ fontSize: 16, color: WB.macFolder }} />
                          <Typography.Text ellipsis style={{ flex: 1, fontSize: 13 }}>{leaf(f.path)}</Typography.Text>
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>文件夹</Typography.Text>
                          <div style={{ display: 'flex', gap: 2 }} onClick={(e) => e.stopPropagation()}>
                            <IconAction title={owner ? '重命名' : '仅可重命名自己创建的'} disabled={!owner} icon={<EditOutlined />} onClick={() => setNameModal({ open: true, mode: 'rename-folder', target: f, value: leaf(f.path) })} />
                            <IconAction title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner} icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'folder', id: f.id, title: leaf(f.path), })} />
                          </div>
                        </div>
                      );
                    })}
                    {(docs ?? []).map((d) => {
                      const owner = isOwner(d.created_by);
                      const busy = !!d.status && d.status !== 'ready' && d.status !== 'failed';
                      const failed = d.status === 'failed';
                      return (
                        <div key={d.id} style={rowStyle(false)}>
                          <FileTextOutlined style={{ fontSize: 16, color: WB.macFile }} />
                          <div style={{ flex: 1, minWidth: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
                            <Typography.Text ellipsis style={{ fontSize: 13 }}>{d.title || d.source}</Typography.Text>
                            {(busy || failed) && (
                              <Tooltip title={failed ? (d.parse_error || '入库失败') : '解析入库进行中'}>
                                <span style={{
                                  fontSize: 10, padding: '1px 6px', borderRadius: 8, flexShrink: 0, lineHeight: '14px',
                                  color: failed ? '#ff3b30' : WB.primary,
                                  background: failed ? '#ff3b301A' : `${WB.primary}1A`,
                                }}>{failed ? '失败' : '解析中'}</span>
                              </Tooltip>
                            )}
                          </div>
                          <Typography.Text type="secondary" style={{ fontSize: 11 }}>{d.source}</Typography.Text>
                          <div style={{ display: 'flex', gap: 2 }} onClick={(e) => e.stopPropagation()}>
                            <IconAction
                              title={busy ? '解析入库中，暂不可编辑' : owner ? '编辑分块' : '仅可编辑自己创建的'}
                              disabled={!owner || busy} icon={<EditOutlined />} onClick={() => setEditDoc(d)}
                            />
                            <IconAction
                              title={busy ? '解析入库中，暂不可重命名' : owner ? '重命名' : '仅可重命名自己创建的'}
                              disabled={!owner || busy} icon={<TagsOutlined />} onClick={() => setNameModal({ open: true, mode: 'rename-doc', target: d, value: d.source, desc: d.title ?? '' })}
                            />
                            <IconAction title={owner ? '删除' : '仅可删除自己创建的'} danger disabled={!owner} icon={<DeleteOutlined />} onClick={() => setConfirm({ kind: 'doc', id: d.id, title: d.title || d.source })} />
                          </div>
                        </div>
                      );
                    })}
                  </>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 新建 / 重命名 模态 */}
      <NameModal
        state={nameModal}
        setState={setNameModal}
        composingRef={composingRef}
        loading={saveColl.isPending || saveFolder.isPending || saveDoc.isPending}
        onOk={submitNameModal}
      />

      {/* 删除确认 */}
      <ConfirmModal
        open={!!confirm}
        title={confirmTitle(confirm)}
        desc={confirm?.kind === 'coll' ? '将一并删除其中所有文件夹与文档' : confirm?.kind === 'folder' ? '将一并删除其下所有子文件夹与文档' : undefined}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />

      {/* 文档分块编辑抽屉 */}
      <DocEditDrawer open={!!editDoc} doc={editDoc} onClose={() => setEditDoc(null)} />

      {/* 文档上传（文件 / 文件夹，解析入库带进度，与管理端一致） */}
      {uploadModal && (
        <div style={modalOverlayStyle} onClick={closeUploadModal}>
          <div style={{ ...modalCardStyle, width: 560 }} onClick={(e) => e.stopPropagation()}>
            <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>
              上传文档
            </div>
            <div style={{ padding: 18 }}>
              <Typography.Text style={{ fontSize: 12, color: '#86868b', display: 'block', marginBottom: 12 }}>
                支持 PDF / Word(docx) / Excel(xlsx/csv) / txt / md / html；上传后自动解析分块嵌入。入库位置：{currentFolder || '根目录'}
              </Typography.Text>
              <Upload.Dragger
                multiple
                showUploadList={false}
                accept={ACCEPT_ATTR}
                beforeUpload={(file) => { handleFiles([file]); return false; }}
              >
                <p className="ant-upload-drag-icon"><InboxOutlined /></p>
                <p className="ant-upload-text" style={{ fontSize: 13 }}>点击或拖拽文件到此处上传</p>
                <p className="ant-upload-hint" style={{ fontSize: 11 }}>支持单文件或批量上传，单文件 ≤ 50MB</p>
              </Upload.Dragger>
              <div style={{ textAlign: 'center', margin: '8px 0' }}>
                <Typography.Text type="secondary" style={{ fontSize: 11 }}>— 或 —</Typography.Text>
              </div>
              <button
                style={{ ...toolBtnStyle, width: '100%', justifyContent: 'center', height: 32 }}
                onClick={() => folderInputRef.current?.click()}
              >
                <FolderOpenOutlined style={{ fontSize: 13 }} /> 上传整个文件夹（保留目录结构）
              </button>
              <input
                ref={(el) => {
                  folderInputRef.current = el;
                  if (el) el.setAttribute('webkitdirectory', '');
                }}
                type="file"
                multiple
                style={{ display: 'none' }}
                onChange={(e) => { handleFolder(e.target.files); e.target.value = ''; }}
              />
              <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: 11, textAlign: 'center' }}>
                浏览器需支持目录选择（Chrome / Edge 支持；Firefox 不支持）
              </Typography.Text>

              {uploadQueue.length > 0 && (
                <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12, maxHeight: '40vh', overflowY: 'auto' }} className="wb-scroll-hide">
                  {uploadQueue.map((it) => {
                    const failed = it.phase === 'failed';
                    const done = it.phase === 'done';
                    return (
                      <div key={it.uid} style={{ border: `1px solid ${WB.border}`, borderRadius: 8, padding: '8px 12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                            {done ? <CheckCircleOutlined style={{ color: '#34c759' }} />
                              : failed ? <CloseCircleOutlined style={{ color: '#ff3b30' }} />
                                : <LoadingOutlined style={{ color: WB.primary }} />}
                            <Typography.Text ellipsis style={{ fontSize: 13, fontWeight: 500 }}>{it.file.name}</Typography.Text>
                          </div>
                          <span style={{
                            fontSize: 11, padding: '1px 8px', borderRadius: 8, flexShrink: 0,
                            color: failed ? '#ff3b30' : done ? '#34c759' : WB.primary,
                            background: failed ? '#ff3b301A' : done ? '#34c7591A' : `${WB.primary}1A`,
                          }}>
                            {PHASE_LABEL[it.phase]}{!done && !failed && it.percent > 0 ? ` ${it.percent}%` : ''}
                          </span>
                        </div>
                        <Progress
                          percent={done ? 100 : failed ? 100 : it.percent}
                          status={failed ? 'exception' : done ? 'success' : 'active'}
                          size="small"
                          strokeColor={WB.primary}
                        />
                        {failed && it.error && (
                          <Typography.Text type="danger" style={{ fontSize: 11 }}>{it.error}</Typography.Text>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 18px 16px' }}>
              <button style={toolBtnStyle} onClick={closeUploadModal}>关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function confirmTitle(c: ConfirmTarget | null): string {
  if (!c) return '';
  const map = { coll: '删除该知识库？', folder: '删除该文件夹？', doc: '删除该文档？' } as const;
  return map[c.kind];
}

// ── MacOS 风格作用域树 ──────────────────────────────────────────────────

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

// ── 新建 / 重命名 模态（MacOS 风格，标题/字段随 mode 动态） ──────────────

interface NameModalState {
  open: boolean;
  mode: 'create-coll' | 'rename-coll' | 'create-folder' | 'rename-folder' | 'create-doc' | 'rename-doc';
  target?: RagCollection | RagFolder | RagDocument | null;
  value: string; desc?: string;
}

function NameModal(props: {
  state: NameModalState;
  setState: (updater: (m: NameModalState) => NameModalState) => void;
  composingRef: { current: boolean };
  loading: boolean;
  onOk: () => void;
}) {
  const { state, setState, composingRef, loading, onOk } = props;
  if (!state.open) return null;

  const META: Record<NameModalState['mode'], { title: string; label: string; placeholder: string; showDesc: boolean; descLabel?: string }> = {
    'create-coll': { title: '新建知识库', label: '名称', placeholder: '知识库名称', showDesc: true, descLabel: '描述' },
    'rename-coll': { title: '重命名知识库', label: '名称', placeholder: '知识库名称', showDesc: true, descLabel: '描述' },
    'create-folder': { title: '新建文件夹', label: '文件夹名', placeholder: 'my-folder', showDesc: false },
    'rename-folder': { title: '重命名文件夹', label: '文件夹名', placeholder: 'my-folder', showDesc: false },
    'create-doc': { title: '新建文档', label: '来源标识', placeholder: 'manual.txt / https://...', showDesc: true, descLabel: '标题' },
    'rename-doc': { title: '重命名文档', label: '来源标识', placeholder: 'manual.txt', showDesc: true, descLabel: '标题' },
  };
  const meta = META[state.mode];

  return (
    <div style={modalOverlayStyle} onClick={() => setState((m) => ({ ...m, open: false }))}>
      <div style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>{meta.title}</div>
        <div style={{ padding: '18px' }}>
          <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>{meta.label}</Typography.Text>
          <Input
            autoFocus
            placeholder={meta.placeholder}
            value={state.value}
            onChange={(e) => setState((m) => ({ ...m, value: e.target.value }))}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setState((m) => ({ ...m, value: (e.target as HTMLInputElement).value })); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              onOk();
            }}
            style={{ fontSize: 13, marginTop: 4 }}
          />
          {meta.showDesc && (
            <>
              <Typography.Text style={{ fontSize: 12, color: '#86868b', marginTop: 12, display: 'block' }}>{meta.descLabel}</Typography.Text>
              <Input
                placeholder={meta.descLabel}
                value={state.desc ?? ''}
                onChange={(e) => setState((m) => ({ ...m, desc: e.target.value }))}
                style={{ fontSize: 13, marginTop: 4 }}
              />
            </>
          )}
          {state.mode === 'create-doc' && (
            <Typography.Text style={{ fontSize: 11, color: '#aeaeb2', display: 'block', marginTop: 10 }}>
              新建后可在「编辑分块」抽屉中填写正文与分块，提交后入库。
            </Typography.Text>
          )}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={() => setState((m) => ({ ...m, open: false }))}>取消</button>
          <button style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }} disabled={loading} onClick={onOk}>
            {loading ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  );
}

function PaneEmpty({ text }: { text: string }) {
  return (
    <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 40 }}>
      {text}
    </div>
  );
}

function IconAction(props: { title: string; icon: ReactNode; onClick: () => void; danger?: boolean; disabled?: boolean }) {
  const { title, icon, onClick, danger, disabled } = props;
  const btn = (
    <button
      style={iconActionBtnStyle(danger, disabled)}
      disabled={disabled}
      onClick={onClick}
    >{icon}</button>
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

const minePillStyle: CSSProperties = {
  fontSize: 10, color: WB.primary, background: `${WB.primary}1A`,
  padding: '1px 6px', borderRadius: 8, flex: '0 0 auto', lineHeight: '14px',
};

const toolbarStyle: CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
  padding: '10px 16px', borderBottom: `1px solid ${WB.border}`, flex: '0 0 auto', gap: 8, flexWrap: 'wrap',
  background: '#fbfbfd',
};

const pathBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, overflow: 'hidden',
  background: '#eef0f3', borderRadius: 6, padding: '4px 10px', height: 28,
  fontSize: 12, color: '#1d1d1f',
};

const pathSegStyle: CSSProperties = {
  cursor: 'pointer', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  display: 'inline-flex', alignItems: 'center', borderRadius: 4, padding: '0 2px',
};

const rowStyle = (_active: boolean): CSSProperties => ({
  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 6,
  cursor: 'pointer', fontSize: 13,
});

const navBtnStyle = (disabled: boolean): CSSProperties => ({
  width: 28, height: 28, borderRadius: 6, border: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 12,
  background: disabled ? 'transparent' : '#eef0f3', color: disabled ? '#c7c7cc' : '#1d1d1f',
  flex: '0 0 28px',
});

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
  width: 400, background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
