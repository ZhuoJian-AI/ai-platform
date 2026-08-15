import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Button, Modal, Form, Input, InputNumber, Typography, Space,
  message, Empty, Tooltip, Tag, Upload, Progress,
} from 'antd';
import {
  PlusOutlined, DeleteOutlined, EditOutlined, SearchOutlined,
  FolderOutlined, FolderAddOutlined, FileOutlined, UploadOutlined,
  SettingOutlined, HomeOutlined, TagOutlined, MinusCircleOutlined,
  BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  ArrowUpOutlined, DatabaseOutlined, InboxOutlined, CheckCircleOutlined,
  CloseCircleOutlined, LoadingOutlined, FolderOpenOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { rag } from '../../api/client';
import type { RagCollection, RagDocument, RagFolder, RagIngestConfig } from '../../api/client';
import { ApiError } from '../../api/client';
import { useOrgTree } from '../../hooks/useOrgTree';
import OrgSelect from '../../components/OrgSelect';
import {
  FinderShell, TitleBar, Sidebar, MacTree, Toolbar, PathBar, NavButton, ToolButton,
  FinderEmpty, FinderLoading, type FinderTreeNode,
} from '../../components/finder/primitives';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { WB, FS } from '../../components/finder/theme';

const { TextArea } = Input;

const DEFAULT_INGEST: RagIngestConfig = {
  embedding_model: 'text-embedding-v4',
  embedding_dim: null,
  chunk_size: 800,
  chunk_overlap: 100,
  top_k: 5,
};

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
const iconForKey = (key: string): ReactNode => NODE_ICON[key.split(':')[0]] ?? <FolderOutlined />;

/** 文档上传入队后的阶段：等待→上传→解析→分块→嵌入→就绪/失败。 */
type UploadPhase = 'queued' | 'uploading' | 'parsing' | 'chunking' | 'embedding' | 'done' | 'failed';
interface UploadItem {
  uid: string;
  file: File;
  phase: UploadPhase;
  percent: number;
  error?: string;
  docId?: string;
  /** 该文件入库到的相对文件夹路径；缺省取当前 currentFolder。文件夹上传时按 webkitRelativePath 还原子目录。 */
  folderPath?: string;
}

/** 支持上传的扩展名（与后端 doc_parser 对齐：pdf/docx/xlsx/csv/txt/md/html）。 */
const ACCEPT_EXTS = [
  'pdf', 'doc', 'docx', 'docm', 'dot', 'dotx', 'dotm', 'rtf', 'odt',
  'xls', 'xlsx', 'xlsm', 'xlsb', 'xlt', 'xltx', 'xltm', 'ods',
  'ppt', 'pptx', 'pptm', 'pps', 'ppsx', 'ppsm', 'pot', 'potx', 'potm', 'odp',
  'csv', 'tsv', 'txt', 'text', 'log', 'md', 'markdown', 'htm', 'html',
];
const ACCEPT_ATTR = ACCEPT_EXTS.map((e) => `.${e}`).join(',');
const _isAccepted = (name: string): boolean => {
  const ext = (name.split('.').pop() || '').toLowerCase();
  return ACCEPT_EXTS.includes(ext);
};

export default function Rag() {
  const qc = useQueryClient();
  const { treeData, nodeMap, isLoading: treeLoading } = useOrgTree();

  // 选中节点 → scope；orgId 由节点携带
  const [scope, setScope] = useState<ScopeState | null>(null);
  const [selectedColl, setSelectedColl] = useState<RagCollection | null>(null);
  const [currentFolder, setCurrentFolder] = useState(''); // "" = 根
  // 当前选中的组织（OrgSelect 切换）；org-scoped 管理员由 OrgSelect 锁定到自己的组织
  const [selectedOrgId, setSelectedOrgId] = useState<string | undefined>();

  // 弹窗
  const [collModal, setCollModal] = useState<{ open: boolean; editing: RagCollection | null }>({ open: false, editing: null });
  const [collForm] = Form.useForm();
  const [folderModal, setFolderModal] = useState<{ open: boolean; editing: RagFolder | null } | null>(null);
  const [folderForm] = Form.useForm();
  // 文档上传弹窗（仅文件上传，已移除「粘贴文本」入口）
  const [uploadModal, setUploadModal] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<UploadItem[]>([]);
  const queueRef = useRef<UploadItem[]>([]);
  const timersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
  const folderInputRef = useRef<HTMLInputElement>(null);
  // 文档重命名（来源标识 / 标题）
  const [renameModal, setRenameModal] = useState<{ open: boolean; doc: RagDocument | null }>({ open: false, doc: null });
  const [renameForm] = Form.useForm();
  const [ingestModal, setIngestModal] = useState(false);
  const [ingestForm] = Form.useForm();
  // 文档分块编辑（重新入库）
  const [contentModal, setContentModal] = useState<{ open: boolean; doc: RagDocument | null }>({ open: false, doc: null });
  const [chunkDrafts, setChunkDrafts] = useState<string[]>([]);
  const [retrieveColl, setRetrieveColl] = useState<RagCollection | null>(null);
  const [queryText, setQueryText] = useState('');
  const [hits, setHits] = useState<{ chunk_id: string; document_id: string | null; content: string; score: number }[]>([]);

  // 仅展示当前选中组织的子树（一次只看一个组织，用 OrgSelect 切换）
  const treeDataScoped = useMemo(() => {
    if (!selectedOrgId) return [];
    return treeData.filter((n) => n.key === `org:${selectedOrgId}`);
  }, [treeData, selectedOrgId]);

  // useOrgTree 树 → FinderTreeNode（按 key 前缀加 scope 图标）
  const finderTree = useMemo((): FinderTreeNode[] => {
    const build = (nodes: typeof treeData): FinderTreeNode[] =>
      nodes.map((n) => ({
        key: n.key,
        label: n.title,
        icon: iconForKey(n.key),
        children: n.children?.length ? build(n.children) : undefined,
      }));
    return build(treeDataScoped);
  }, [treeDataScoped]);

  const selectedKey = scope ? `${SCOPE_PREFIX[scope.scope_type]}:${scope.scope_id ?? scope.orgId}` : null;

  // 切换组织时默认选中该组织根节点（org-scoped 管理员由 OrgSelect 锁定到自己的组织）
  useEffect(() => {
    if (!selectedOrgId || treeLoading) return;
    const info = nodeMap.get(`org:${selectedOrgId}`);
    if (!info) return;
    setSelectedColl(null);
    setCurrentFolder('');
    setScope({ scope_type: 'organization', scope_id: null, orgId: info.orgId, nodeName: info.name });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrgId, treeLoading]);

  const orgId = scope?.orgId;

  // 组织级入库参数（新建知识库默认值）
  const { data: ingestCfg } = useQuery({
    queryKey: ['rag-ingest-config', orgId],
    queryFn: () => rag.getIngestConfig(orgId!),
    enabled: !!orgId,
  });
  const effectiveIngest = ingestCfg ?? DEFAULT_INGEST;

  // 中栏：当前 scope 下的集合
  const { data: collections, isLoading: collLoading } = useQuery({
    queryKey: ['rag', scope?.orgId, scope?.scope_type, scope?.scope_id],
    queryFn: () => rag.listCollections(scope!.orgId, { scope_type: scope!.scope_type, scope_id: scope!.scope_id ?? null }),
    enabled: !!scope,
  });

  // 右栏：当前集合 + 当前文件夹
  const { data: folders } = useQuery({
    queryKey: ['rag-folders', selectedColl?.id, currentFolder],
    queryFn: () => rag.listFolders(selectedColl!.id, currentFolder),
    enabled: !!selectedColl,
  });
  const { data: docs } = useQuery({
    queryKey: ['rag-docs', selectedColl?.id, currentFolder],
    queryFn: () => rag.listDocuments(selectedColl!.id, currentFolder),
    enabled: !!selectedColl,
  });

  // 切换集合时回到根目录
  useEffect(() => { setCurrentFolder(''); }, [selectedColl?.id]);

  // ── 集合 增/改/删 ──
  const saveColl = useMutation({
    mutationFn: (v: { name: string; description?: string | null; chunk_size: number; chunk_overlap: number }) => {
      const editing = collModal.editing;
      const payload = { name: v.name, description: v.description ?? null, chunk_size: v.chunk_size, chunk_overlap: v.chunk_overlap };
      if (editing) return rag.updateCollection(editing.id, payload);
      return rag.createCollection(scope!.orgId, {
        name: v.name, description: v.description ?? null,
        embedding_model: effectiveIngest.embedding_model, embedding_dim: effectiveIngest.embedding_dim,
        chunk_size: v.chunk_size, chunk_overlap: v.chunk_overlap,
        scope_type: scope!.scope_type, scope_id: scope!.scope_id ?? null,
      });
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag'] }); setCollModal({ open: false, editing: null }); message.success('已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const delColl = useMutation({
    mutationFn: (id: string) => rag.deleteCollection(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag'] }); if (selectedColl) setSelectedColl(null); message.success('已删除'); },
    onError: () => message.error('删除失败'),
  });

  // ── 文件夹 增/改/删 ──
  const saveFolder = useMutation({
    mutationFn: (v: { name: string }) => {
      const editing = folderModal?.editing;
      const name = String(v.name).trim();
      const path = currentFolder ? `${currentFolder}/${name}` : name;
      if (editing) return rag.renameFolder(editing.id, path);
      return rag.createFolder(selectedColl!.id, path);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag-folders'] }); qc.invalidateQueries({ queryKey: ['rag-docs'] }); setFolderModal(null); message.success('已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '操作失败'),
  });
  const delFolder = useMutation({
    mutationFn: (id: string) => rag.deleteFolder(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag-folders'] }); qc.invalidateQueries({ queryKey: ['rag-docs'] }); message.success('已删除'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  // ── 文档 重命名 / 删除（上传走独立流程，见 uploadQueue） ──
  const renameDoc = useMutation({
    mutationFn: (v: { source: string; title?: string | null }) =>
      rag.updateDocument(renameModal.doc!.id, { source: v.source, title: v.title ?? null }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag-docs'] }); setRenameModal({ open: false, doc: null }); message.success('已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  const delDoc = useMutation({
    mutationFn: (id: string) => rag.deleteDocument(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag-docs'] }); message.success('已删除'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除失败'),
  });

  // ── 文档分块编辑 / 重新入库 ──
  const { data: chunkList, isLoading: chunksLoading } = useQuery({
    queryKey: ['rag-chunks', contentModal.doc?.id],
    queryFn: () => rag.listChunks(contentModal.doc!.id),
    enabled: !!contentModal.open && !!contentModal.doc,
  });
  // 分块加载后初始化可编辑草稿
  useEffect(() => {
    if (contentModal.open && chunkList) {
      setChunkDrafts(chunkList.map((c) => c.content));
    }
  }, [contentModal.open, chunkList]);
  const reingest = useMutation({
    mutationFn: (v: { chunks: string[]; source: string; title?: string | null }) =>
      rag.reingestDocument(contentModal.doc!.id, { chunks: v.chunks, source: v.source, title: v.title ?? null }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rag-docs'] });
      qc.invalidateQueries({ queryKey: ['rag-chunks'] });
      setContentModal({ open: false, doc: null });
      message.success('已重新入库（分块 + 嵌入）');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重新入库失败'),
  });
  // 从原文重切：用服务端结构感知分块器对 doc.content 重新切分（不修改原文）
  const rechunk = useMutation({
    mutationFn: () => rag.reingestDocument(contentModal.doc!.id, { chunks: null, source: contentModal.doc!.source }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['rag-docs'] });
      qc.invalidateQueries({ queryKey: ['rag-chunks'] });
      message.success('已从原文重新分块 + 嵌入');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '重切失败'),
  });

  // ── 入库参数配置 ──
  const saveIngest = useMutation({
    mutationFn: (v: RagIngestConfig) => rag.setIngestConfig(orgId!, v),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rag-ingest-config'] }); setIngestModal(false); message.success('默认入库参数已保存'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '保存失败'),
  });
  useEffect(() => { if (ingestModal && ingestCfg) ingestForm.setFieldsValue(ingestCfg); }, [ingestModal, ingestCfg, ingestForm]);

  // ── 检索测试 ──
  const doRetrieve = useMutation({
    mutationFn: () => rag.retrieve(retrieveColl!.id, queryText, effectiveIngest.top_k),
    onSuccess: (r) => { setHits(r.hits); if (!r.hits.length) message.info('无命中'); },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '检索失败'),
  });

  // ── 文件上传队列：上传 → 解析 → 分块 → 嵌入 → 就绪，全程进度 ──
  const phaseLabel: Record<UploadPhase, string> = {
    queued: '等待中', uploading: '上传中', parsing: '解析中',
    chunking: '分块中', embedding: '嵌入中', done: '就绪', failed: '失败',
  };
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
        const s = await rag.getDocumentStatus(docId);
        const phase: UploadPhase =
          s.status === 'pending' ? 'parsing'
          : s.status === 'parsing' ? 'parsing'
          : s.status === 'chunking' ? 'chunking'
          : s.status === 'embedding' ? 'embedding'
          : s.status === 'ready' ? 'done'
          : s.status === 'failed' ? 'failed' : 'embedding';
        upsert(uid, { phase, percent: s.progress });
        if (s.status === 'ready') { stopPoll(uid); startNext(); }
        else if (s.status === 'failed') { stopPoll(uid); upsert(uid, { error: s.parse_error ?? '入库失败' }); startNext(); }
        else pollStatus(uid, docId);
      } catch {
        // 网络抖动：1.5s 后重试
        timersRef.current[uid] = setTimeout(() => pollStatus(uid, docId), 1500);
      }
    }, 1200);
  };
  const processOne = async (item: UploadItem) => {
    try {
      const doc = await rag.uploadDocumentFile(
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
      // 全部落定：刷新列表
      if (queueRef.current.length && queueRef.current.every((it) => it.phase === 'done' || it.phase === 'failed')) {
        qc.invalidateQueries({ queryKey: ['rag-docs'] });
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
      file: f, phase: 'queued' as UploadPhase, percent: 0,
      folderPath: currentFolder,
    })));
  };
  /** 文件夹上传：按 webkitRelativePath 还原子目录，并入当前 folder_path。
   *  路径形如 ``root/sub/a.txt`` → folder_path = ``{currentFolder}/root/sub``（保留根目录名）。 */
  const handleFolder = (fileList: FileList | null) => {
    if (!fileList || !fileList.length) return;
    const items: UploadItem[] = [];
    let skipped = 0;
    Array.from(fileList).forEach((f) => {
      if (!_isAccepted(f.name)) { skipped += 1; return; }
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      const slash = rel.lastIndexOf('/');
      const subDir = slash >= 0 ? rel.slice(0, slash) : '';
      const folderPath = subDir ? (currentFolder ? `${currentFolder}/${subDir}` : subDir) : currentFolder;
      items.push({
        uid: `${rel}-${f.size}-${Math.random().toString(36).slice(2, 6)}`,
        file: f, phase: 'queued' as UploadPhase, percent: 0, folderPath,
      });
    });
    if (skipped > 0) message.info(`已跳过 ${skipped} 个不支持的文件（支持 PDF / Word / Excel / PowerPoint / 文本 / HTML）`);
    enqueue(items);
  };
  const closeUploadModal = () => {
    Object.keys(timersRef.current).forEach(stopPoll);
    setUploadModal(false);
  };
  // 卸载时清理轮询定时器
  useEffect(() => () => { Object.keys(timersRef.current).forEach(stopPoll); }, []);

  // 路径段
  const folderSegs = currentFolder ? currentFolder.split('/') : [];

  // 删除确认：界面正中 ConfirmModal（不再用悬浮 Popconfirm）
  const [confirm, setConfirm] = useState<{ kind: 'coll' | 'folder' | 'doc'; id: string; title: string; desc?: string } | null>(null);
  const confirmLoading = confirm?.kind === 'coll' ? delColl.isPending : confirm?.kind === 'folder' ? delFolder.isPending : confirm?.kind === 'doc' ? delDoc.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'coll') delColl.mutate(confirm.id);
    else if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else delDoc.mutate(confirm.id);
    setConfirm(null);
  };

  // 集合弹窗初始值
  useEffect(() => {
    if (collModal.open) {
      if (collModal.editing) {
        collForm.setFieldsValue(collModal.editing);
      } else {
        collForm.setFieldsValue({
          chunk_size: effectiveIngest.chunk_size, chunk_overlap: effectiveIngest.chunk_overlap,
        });
      }
    }
  }, [collModal, collForm, effectiveIngest]);

  const openCollCreate = () => {
    if (!scope) { message.warning('请先在左侧选择组织 / 部门 / 团队 / 个人节点'); return; }
    setCollModal({ open: true, editing: null });
  };
  const openCollEdit = (r: RagCollection) => setCollModal({ open: true, editing: r });

  const openFolderCreate = () => setFolderModal({ open: true, editing: null });
  const openFolderRename = (f: RagFolder) => {
    const name = f.path.includes('/') ? f.path.slice(f.path.lastIndexOf('/') + 1) : f.path;
    folderForm.setFieldsValue({ name });
    setFolderModal({ open: true, editing: f });
  };

  const openDocUpload = () => { setUploadQueue([]); queueRef.current = []; setUploadModal(true); };
  const openDocRename = (d: RagDocument) => {
    renameForm.setFieldsValue({ source: d.source, title: d.title ?? '' });
    setRenameModal({ open: true, doc: d });
  };
  const openDocEdit = (d: RagDocument) => {
    setChunkDrafts([]);
    setContentModal({ open: true, doc: d });
  };

  const collName = (f: RagFolder) => f.path.includes('/') ? f.path.slice(f.path.lastIndexOf('/') + 1) : f.path;

  return (
    <FinderShell style={{ height: 'calc(100vh - 64px)' }}>
      <TitleBar
        icon={<DatabaseOutlined />}
        title="RAG 知识库"
        titleExtra={<OrgSelect value={selectedOrgId} onChange={setSelectedOrgId} />}
        extra={
          <>
            {scope && <Tag color="blue" style={{ marginInlineEnd: 0 }}>{scope.nodeName}</Tag>}
            <ToolButton icon={<SettingOutlined style={{ fontSize: 13 }} />} onClick={() => setIngestModal(true)} disabled={!orgId}>
              入库参数
            </ToolButton>
          </>
        }
      />

      {/* 三栏：组织架构 · 知识库 · 文档与文件夹 */}
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
                setSelectedColl(null);
                setCurrentFolder('');
                setScope({
                  scope_type: info.type,
                  scope_id: info.type === 'organization' ? null : info.id,
                  orgId: info.orgId,
                  nodeName: info.name,
                });
              }}
            />
          )}
        </Sidebar>

        {/* 中栏：知识库 */}
        <section style={{ flex: 3, minWidth: 0, display: 'flex', flexDirection: 'column', borderRight: `1px solid ${WB.border}` }}>
          <Toolbar
            left={<span style={{ fontSize: FS.body, fontWeight: 600, color: WB.text }}>知识库</span>}
            right={<ToolButton primary icon={<PlusOutlined style={{ fontSize: 13 }} />} onClick={openCollCreate} disabled={!scope}>新建</ToolButton>}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!scope ? (
              <FinderEmpty description="请从左侧选择节点" />
            ) : collLoading ? <FinderLoading /> : (collections?.length === 0) ? (
              <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>该节点下暂无知识库</div>
            ) : (
              (collections ?? []).map((r) => {
                const active = selectedColl?.id === r.id;
                return (
                  <div
                    key={r.id}
                    onClick={() => setSelectedColl(r)}
                    onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                    onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6,
                      cursor: 'pointer', fontSize: FS.body, lineHeight: 1,
                      background: active ? WB.activeBg : 'transparent',
                      color: active ? WB.primary : WB.text, fontWeight: active ? 600 : 400,
                    }}
                  >
                    <FolderOutlined style={{ fontSize: 15, color: active ? WB.primary : '#faad14', flex: '0 0 auto' }} />
                    <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                    <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                      <Tooltip title="检索测试"><ActionBtn icon={<SearchOutlined />} onClick={() => { setRetrieveColl(r); setHits([]); setQueryText(''); }} /></Tooltip>
                      <Tooltip title="重命名"><ActionBtn icon={<EditOutlined />} onClick={() => openCollEdit(r)} /></Tooltip>
                      <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'coll', id: r.id, title: '删除该知识库及其所有文档？' })} />
                    </span>
                  </div>
                );
              })
            )}
          </div>
        </section>

        {/* 右栏：文档与文件夹 */}
        <section style={{ flex: 5, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          <Toolbar
            left={
              <>
                <NavButton icon={<ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} />} disabled={!currentFolder} onClick={() => setCurrentFolder(currentFolder.includes('/') ? currentFolder.slice(0, currentFolder.lastIndexOf('/')) : '')} title="返回上一级" />
                {selectedColl ? (
                  <PathBar
                    rootLabel={selectedColl.name}
                    rootIcon={<HomeOutlined style={{ fontSize: 12 }} />}
                    segs={folderSegs}
                    onSeg={(i) => setCurrentFolder(i < 0 ? '' : folderSegs.slice(0, i + 1).join('/'))}
                  />
                ) : <span style={{ fontSize: FS.aux, color: WB.textAux }}>文档与文件夹</span>}
              </>
            }
            right={selectedColl && (
              <>
                <ToolButton icon={<FolderAddOutlined style={{ fontSize: 13 }} />} onClick={openFolderCreate}>新建文件夹</ToolButton>
                <ToolButton primary icon={<UploadOutlined style={{ fontSize: 13 }} />} onClick={openDocUpload}>上传文档</ToolButton>
              </>
            )}
          />
          <div style={{ flex: 1, overflowY: 'auto', padding: '4px 0' }} className="wb-scroll-hide">
            {!selectedColl ? (
              <FinderEmpty description="请从中栏选择知识库" />
            ) : (folders?.length === 0 && docs?.length === 0) ? (
              <div style={{ textAlign: 'center', color: WB.textAux, fontSize: FS.body, marginTop: 40 }}>此处暂无文件夹 / 文档</div>
            ) : (
              [
                ...(folders ?? []).map((f) => ({ kind: 'folder' as const, id: f.id, name: collName(f), ref: f as RagFolder })),
                ...(docs ?? []).map((d) => ({ kind: 'doc' as const, id: d.id, name: d.title || d.source, ref: d as RagDocument })),
              ].map((item) => (
                <div
                  key={`${item.kind}:${item.id}`}
                  onClick={() => { if (item.kind === 'folder') setCurrentFolder((item.ref as RagFolder).path); }}
                  onMouseEnter={(e) => { e.currentTarget.style.background = WB.hover; }}
                  onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px', margin: '1px 6px', borderRadius: 6, cursor: item.kind === 'folder' ? 'pointer' : 'default', fontSize: FS.body, lineHeight: 1.3 }}
                >
                  {item.kind === 'folder'
                    ? <FolderOutlined style={{ fontSize: 15, color: '#8c8c8c', flex: '0 0 auto' }} />
                    : <FileOutlined style={{ fontSize: 15, color: '#8c8c8c', flex: '0 0 auto' }} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: WB.text }}>{item.name}</span>
                      {item.kind === 'doc' && (() => {
                        const d = item.ref as RagDocument;
                        if (!d.status || d.status === 'ready') return null;
                        const failed = d.status === 'failed';
                        return (
                          <Tooltip title={failed ? (d.parse_error || '入库失败') : '解析入库进行中'}>
                            <Tag color={failed ? 'red' : 'blue'} style={{ marginInlineEnd: 0, fontSize: FS.micro, lineHeight: '16px', padding: '0 4px' }}>
                              {failed ? '失败' : '解析中'}
                            </Tag>
                          </Tooltip>
                        );
                      })()}
                    </div>
                    <div style={{ fontSize: FS.micro, color: WB.textAux, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.kind === 'doc'
                        ? `来源：${(item.ref as RagDocument).source} · ${(item.ref as RagDocument).content?.length ?? 0} 字`
                        : '文件夹'}
                    </div>
                  </div>
                  <span style={{ display: 'flex', gap: 2, flex: '0 0 auto' }} onClick={(e) => e.stopPropagation()}>
                    {item.kind === 'folder' ? (
                      <>
                        <Tooltip title="重命名"><ActionBtn icon={<EditOutlined />} onClick={() => openFolderRename(item.ref as RagFolder)} /></Tooltip>
                        <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'folder', id: (item.ref as RagFolder).id, title: '删除该文件夹及其下所有内容？' })} />
                      </>
                    ) : (() => {
                      const d = item.ref as RagDocument;
                      const busy = !!d.status && d.status !== 'ready' && d.status !== 'failed';
                      return (
                        <>
                          <Tooltip title={busy ? '解析入库中，暂不可编辑' : '编辑内容（分块）'}>
                            <ActionBtn icon={<EditOutlined />} disabled={busy} onClick={() => openDocEdit(d)} />
                          </Tooltip>
                          <Tooltip title={busy ? '解析入库中，暂不可重命名' : '重命名'}>
                            <ActionBtn icon={<TagOutlined />} disabled={busy} onClick={() => openDocRename(d)} />
                          </Tooltip>
                          <ActionBtn icon={<DeleteOutlined />} danger onClick={() => setConfirm({ kind: 'doc', id: d.id, title: '删除该文档？' })} />
                        </>
                      );
                    })()}
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>

      {/* 知识库 新建/重命名 */}
      <Modal
        title={collModal.editing ? '重命名知识库' : '新建知识库'} open={collModal.open}
        onCancel={() => setCollModal({ open: false, editing: null })}
        onOk={() => collForm.submit()} confirmLoading={saveColl.isPending} width={520}
      >
        <Form form={collForm} layout="vertical" onFinish={(v) => saveColl.mutate(v)}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Space>
            <Form.Item name="chunk_size" label="分块大小"><InputNumber min={50} /></Form.Item>
            <Form.Item name="chunk_overlap" label="重叠"><InputNumber min={0} /></Form.Item>
          </Space>
          {!collModal.editing && (
            <Typography.Text type="secondary">
              嵌入模型：{effectiveIngest.embedding_model}；作用域：{scope?.scope_type}（可在右上「入库参数」调整默认参数）
            </Typography.Text>
          )}
        </Form>
      </Modal>

      {/* 文件夹 新建/重命名 */}
      <Modal
        title={folderModal?.editing ? '重命名文件夹' : '新建文件夹'} open={!!folderModal}
        onCancel={() => setFolderModal(null)}
        onOk={() => folderForm.submit()} confirmLoading={saveFolder.isPending} width={420}
      >
        <Form form={folderForm} layout="vertical" onFinish={(v) => saveFolder.mutate(v)}>
          <Form.Item name="name" label="文件夹名" rules={[{ required: true }]}><Input placeholder="my-folder" /></Form.Item>
          <Typography.Text type="secondary">位置：{currentFolder || '根目录'}</Typography.Text>
        </Form>
      </Modal>

      {/* 文档 上传（文件） */}
      <Modal
        title="上传文档" open={uploadModal} onCancel={closeUploadModal}
        footer={<Button onClick={closeUploadModal}>关闭</Button>} width={620}
        maskClosable={false}
      >
        <Typography.Paragraph type="secondary" style={{ marginBottom: 12 }}>
          支持 PDF / Word / Excel / PowerPoint / 文本与网页文件；上传后自动解析分块嵌入。入库位置：{currentFolder || '根目录'}
        </Typography.Paragraph>
        <Upload.Dragger
          multiple
          showUploadList={false}
          accept={ACCEPT_ATTR}
          beforeUpload={(file) => { handleFiles([file]); return false; }}
        >
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
          <p className="ant-upload-hint">支持单文件或批量上传，单文件 ≤ 50MB</p>
        </Upload.Dragger>
        <div style={{ textAlign: 'center', margin: '8px 0' }}>
          <Typography.Text type="secondary" style={{ fontSize: FS.aux }}>— 或 —</Typography.Text>
        </div>
        <Button
          block icon={<FolderOpenOutlined />} onClick={() => folderInputRef.current?.click()}
        >
          上传整个文件夹（保留目录结构）
        </Button>
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
        <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6, fontSize: FS.micro, textAlign: 'center' }}>
          浏览器需支持目录选择（Chrome / Edge 支持；Firefox 不支持）
        </Typography.Text>
        {uploadQueue.length > 0 && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {uploadQueue.map((it) => {
              const failed = it.phase === 'failed';
              const done = it.phase === 'done';
              return (
                <div key={it.uid} style={{ border: `1px solid ${WB.border}`, borderRadius: 6, padding: '8px 12px' }}>
                  <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 6 }}>
                    <Space size={6}>
                      {done ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        : failed ? <CloseCircleOutlined style={{ color: WB.danger }} />
                        : <LoadingOutlined style={{ color: WB.primary }} />}
                      <Typography.Text style={{ fontSize: FS.body, fontWeight: 500 }} ellipsis>
                        {it.file.name}
                      </Typography.Text>
                    </Space>
                    <Tag color={failed ? 'red' : done ? 'green' : 'blue'} style={{ marginInlineEnd: 0 }}>
                      {phaseLabel[it.phase]}{!done && !failed && it.percent > 0 ? ` ${it.percent}%` : ''}
                    </Tag>
                  </Space>
                  <Progress
                    percent={done ? 100 : failed ? 100 : it.percent}
                    status={failed ? 'exception' : done ? 'success' : 'active'}
                    size="small"
                  />
                  {failed && it.error && (
                    <Typography.Text type="danger" style={{ fontSize: FS.micro }}>{it.error}</Typography.Text>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Modal>

      {/* 文档 重命名（来源标识 / 标题） */}
      <Modal
        title="重命名文档" open={renameModal.open}
        onCancel={() => setRenameModal({ open: false, doc: null })}
        onOk={() => renameForm.submit()} confirmLoading={renameDoc.isPending} width={520}
      >
        <Form form={renameForm} layout="vertical" onFinish={(v) => renameDoc.mutate(v)}>
          <Form.Item name="source" label="来源标识" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="title" label="标题"><Input /></Form.Item>
        </Form>
      </Modal>

      {/* 文档分块编辑 / 重新入库 */}
      <Modal
        title={`编辑文档（分块）· ${contentModal.doc?.title || contentModal.doc?.source || ''}`}
        open={contentModal.open}
        onCancel={() => setContentModal({ open: false, doc: null })}
        onOk={() => reingest.mutate({
          chunks: chunkDrafts,
          source: contentModal.doc!.source,
          title: contentModal.doc!.title,
        })}
        confirmLoading={reingest.isPending}
        width={780}
        okText="重新入库"
      >
        <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 8 }}>
          <Typography.Text type="secondary">
            以下即文档当前的分块；可编辑、增删分块，保存后将删除旧分块并按此重新分块嵌入。
          </Typography.Text>
          <Space>
            <Button
              size="small"
              loading={rechunk.isPending}
              onClick={() => rechunk.mutate()}
              title="用结构感知分块器对原文重新切分（标题随正文、代码块不拆），无需重新上传"
            >
              从原文重切
            </Button>
            <Button size="small" icon={<PlusOutlined />} onClick={() => setChunkDrafts([...chunkDrafts, ''])}>添加分块</Button>
          </Space>
        </Space>
        {chunksLoading ? (
          <Typography.Text type="secondary">加载分块中…</Typography.Text>
        ) : chunkDrafts.length === 0 ? (
          <Empty description="该文档暂无分块" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div style={{ maxHeight: '55vh', overflow: 'auto', paddingRight: 4 }}>
            {chunkDrafts.map((text, i) => (
              <div key={i} style={{ marginBottom: 12, border: `1px solid ${WB.border}`, borderRadius: 6, padding: 8 }}>
                <Space style={{ width: '100%', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Typography.Text type="secondary">分块 #{i + 1} · {text.length} 字</Typography.Text>
                  <Button size="small" type="text" danger icon={<MinusCircleOutlined />}
                    onClick={() => setChunkDrafts(chunkDrafts.filter((_, idx) => idx !== i))} />
                </Space>
                <TextArea
                  value={text}
                  onChange={(e) => setChunkDrafts(chunkDrafts.map((c, idx) => (idx === i ? e.target.value : c)))}
                  autoSize={{ minRows: 2, maxRows: 10 }}
                />
              </div>
            ))}
          </div>
        )}
      </Modal>

      {/* 入库参数配置 */}
      <Modal
        title="文档入库参数配置（组织级默认）" open={ingestModal}
        onCancel={() => setIngestModal(false)}
        onOk={() => ingestForm.submit()} confirmLoading={saveIngest.isPending} width={520}
      >
        <Typography.Paragraph type="secondary">
          作为本组织新建知识库与文档入库的默认参数；已存在的知识库不受影响。
        </Typography.Paragraph>
        <Form form={ingestForm} layout="vertical" onFinish={(v) => saveIngest.mutate(v)} initialValues={DEFAULT_INGEST}>
          <Form.Item name="embedding_model" label="嵌入模型" rules={[{ required: true }]}><Input /></Form.Item>
          <Space>
            <Form.Item name="chunk_size" label="分块大小"><InputNumber min={50} /></Form.Item>
            <Form.Item name="chunk_overlap" label="重叠"><InputNumber min={0} /></Form.Item>
            <Form.Item name="top_k" label="检索 Top-K"><InputNumber min={1} max={50} /></Form.Item>
          </Space>
        </Form>
      </Modal>

      {/* 检索测试 */}
      <Modal title={`检索测试 · ${retrieveColl?.name ?? ''}`} open={!!retrieveColl}
        onCancel={() => setRetrieveColl(null)} footer={null} width={720}>
        <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
          <Input placeholder="输入查询文本" value={queryText} onChange={(e) => setQueryText(e.target.value)} onPressEnter={() => doRetrieve.mutate()} />
          <Button type="primary" icon={<SearchOutlined />} loading={doRetrieve.isPending} onClick={() => doRetrieve.mutate()}>检索</Button>
        </Space.Compact>
        {hits.length === 0 ? (
          <Empty description="无命中或未配置嵌入 provider" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : hits.map((h) => (
          <div key={h.chunk_id} style={{ padding: '8px 0', borderBottom: `1px solid ${WB.border}` }}>
            <div style={{ fontSize: FS.micro, color: WB.textAux, marginBottom: 4 }}>score={h.score.toFixed(4)} · doc={h.document_id ?? '-'}</div>
            <Typography.Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: FS.body }}>{h.content}</Typography.Paragraph>
          </div>
        ))}
      </Modal>

      {/* 删除确认：界面正中模态 */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.title ?? ''}
        desc={confirm?.desc}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />
    </FinderShell>
  );
}

/** 紧凑行内动作按钮（图标按钮，13px）。 */
function ActionBtn({ icon, danger, disabled, onClick, title }: {
  icon: ReactNode; danger?: boolean; disabled?: boolean; onClick?: () => void; title?: string;
}) {
  return (
    <Tooltip title={title}>
      <button
        onClick={onClick}
        disabled={disabled}
        style={{
          width: 24, height: 24, borderRadius: 5, border: 'none',
          cursor: disabled ? 'not-allowed' : 'pointer',
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 13,
          background: 'transparent',
          color: disabled ? '#d0d0d0' : danger ? WB.danger : WB.textAux,
        }}
      >
        {icon}
      </button>
    </Tooltip>
  );
}
