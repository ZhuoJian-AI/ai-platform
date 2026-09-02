import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import {
  Input, Typography, message, Empty, Spin, Select, Checkbox, Modal, List, Dropdown,
} from 'antd';
import {
  DeleteOutlined, BankOutlined, ApartmentOutlined, TeamOutlined, UserOutlined,
  FolderOutlined, FileTextOutlined, FolderAddOutlined, ArrowUpOutlined,
  HomeOutlined, UploadOutlined, EyeOutlined, RightOutlined,
  AppstoreOutlined, UnorderedListOutlined, SearchOutlined, CheckSquareOutlined,
  HistoryOutlined, RestOutlined, ShareAltOutlined, SendOutlined, AuditOutlined, MoreOutlined,
} from '@ant-design/icons';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  terminal, WORKSPACE_MAX_FILE_BYTES, type Workspace, type WorkspaceFile, type WorkspaceFileListItem, type WorkspaceFolder, type TerminalResources,
} from '../../api/client';
import { ApiError } from '../../api/client';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from './BrowserDrawer';
import ConfirmModal from '../../components/finder/ConfirmModal';
import { auditSummary, auditTitle, workspaceDisplayName, workspaceSourceLabel, workspaceVisiblePath } from '../../utils/workspacePresentation';
import {
  useWorkspaceUploadQueue, WorkspaceUploadPicker, WorkspaceUploadQueueStatus,
} from '../../components/files/WorkspaceUploadQueue';
// extOf 已由 classifyFile 内部使用，此处不再直接引用

/** WorkBuddy 配色（与 Terminal.tsx 保持一致）。 */
const WB = {
  primary: '#6366F1', primaryHover: '#818CF8',
  sidebar: '#F5F5F7', hover: '#ECECEF', border: '#E5E7EB',
  macFolder: '#5AC8FA', macFile: '#6366F1',
};

/** 统一字体栈：与终端 Terminal.tsx 完全一致，根容器设置后所有子文本继承。 */
const WB_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif';

const SCOPE_ORDER = ['organization', 'department', 'team', 'user'] as const;
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
  wsId: string;
  children?: TreeNode[];
}

/** 把用户可见的扁平工作空间列表组织成树。
 *
 * 一个角色可能同时获授多个部门工作空间，不能按 scope_type 只保留第一项。
 * 当前用户的个人空间挂在其主部门下；无法确认父级的团队/个人空间仍保留在组织根节点下。
 */
function buildTree(
  workspaces: Workspace[],
  homeDepartmentId?: string | null,
  homeTeamId?: string | null,
): { treeData: TreeNode[]; wsById: Map<string, Workspace> } {
  const wsById = new Map<string, Workspace>();
  for (const w of workspaces) wsById.set(w.id, w);
  const toNode = (w: Workspace): TreeNode => ({
    key: `ws:${w.id}`,
    name: w.name,
    scope: w.scope_type,
    wsId: w.id,
  });

  const departments = workspaces
    .filter((w) => w.scope_type === 'department')
    .map(toNode);
  const homeDepartment = departments.find((node) => wsById.get(node.wsId)?.scope_id === homeDepartmentId);
  const teams = workspaces.filter((w) => w.scope_type === 'team').map(toNode);
  const homeTeam = teams.find((node) => wsById.get(node.wsId)?.scope_id === homeTeamId);
  const people = workspaces.filter((w) => w.scope_type === 'user').map(toNode);
  if (homeTeam && people.length) homeTeam.children = people;
  else if (homeDepartment && people.length) homeDepartment.children = people;
  if (homeDepartment && homeTeam) {
    homeDepartment.children = [homeTeam, ...(homeDepartment.children ?? [])];
  }

  const rootChildren = [
    ...departments,
    ...teams.filter((node) => node !== homeTeam),
    ...(homeDepartment || homeTeam ? [] : people),
  ];
  const organizations = workspaces.filter((w) => w.scope_type === 'organization').map(toNode);
  if (organizations.length) {
    organizations[0].children = [
      ...(organizations[0].children ?? []),
      ...rootChildren,
    ];
    return { treeData: [...organizations, ...workspaces.filter((w) => !SCOPE_ORDER.includes(w.scope_type as typeof SCOPE_ORDER[number])).map(toNode)], wsById };
  }
  return { treeData: rootChildren, wsById };
}

/** 文件扩展名（小写、无点）。 */
function fileName(path: string): string {
  return path.split('/').pop() || path;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fileType(path: string): string {
  const name = fileName(path);
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1).toUpperCase() : '文件';
}

const PARSE_LABEL: Record<string, string> = {
  queued: '等待解析', processing: '解析中', ready: '可使用', failed: '解析失败', unsupported: '不支持解析', unparsed: '未解析',
};

/** 工作空间管理视图：MacOS Finder 风格。
 *  左栏（2:8）为用户权限可见的工作空间树（组织→部门→团队→个人，逐级嵌套）；
 *  右栏为选中工作空间的文件夹 / 文件图标浏览器。
 *  全部字体沿用终端 WB_FONT，字号与终端一致（标题 14 / 主文本 13 / 辅助 12 / 微 11）。 */
export default function WorkspaceManagerView({
  resources,
  homeDepartmentId,
  homeTeamId,
}: {
  resources: TerminalResources | undefined;
  homeDepartmentId?: string | null;
  homeTeamId?: string | null;
}) {
  const qc = useQueryClient();
  const [urlParams, setUrlParams] = useSearchParams();
  const workspaces = resources?.workspaces ?? [];
  const { treeData, wsById } = useMemo(
    () => buildTree(workspaces, homeDepartmentId, homeTeamId),
    [homeDepartmentId, homeTeamId, workspaces],
  );

  // 默认选中用户个人工作空间（或 defaults.workspace_id，或首个可见工作空间）
  const defaultWsId = resources?.defaults?.workspace_id
    ?? workspaces.find((w) => w.scope_type === 'user')?.id
    ?? workspaces[0]?.id
    ?? null;
  const [selectedWsId, setSelectedWsId] = useState<string | null>(() => urlParams.get('workspace'));
  useEffect(() => {
    if ((!selectedWsId || !wsById.has(selectedWsId)) && defaultWsId) setSelectedWsId(defaultWsId);
  }, [defaultWsId, selectedWsId, wsById]);
  const selectedWs = selectedWsId ? wsById.get(selectedWsId) ?? null : null;
  const canCreate = selectedWs?.capabilities?.create ?? false;
  const canManage = selectedWs?.capabilities?.manage ?? false;

  const [cwd, setCwd] = useState<string[]>(() => (urlParams.get('path') || '').split('/').filter(Boolean));
  const previousWsRef = useRef<string | null>(selectedWsId);
  const [folderModalOpen, setFolderModalOpen] = useState(false);
  const [folderName, setFolderName] = useState('');
  const [hovered, setHovered] = useState<string | null>(null);
  const [focused, setFocused] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'time' | 'type' | 'size'>('name');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [selecting, setSelecting] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const fileAreaRef = useRef<HTMLDivElement>(null);
  const dragSelectionRef = useRef<{
    pointerId: number; startX: number; startY: number; baseSelection: Set<string>;
  } | null>(null);
  const [marquee, setMarquee] = useState<{ left: number; top: number; width: number; height: number } | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [auditOpen, setAuditOpen] = useState(false);
  const [versionFile, setVersionFile] = useState<WorkspaceFileListItem | null>(null);
  const [publishFile, setPublishFile] = useState<WorkspaceFileListItem | null>(null);
  const [publishTarget, setPublishTarget] = useState<string | undefined>();
  const composingRef = useRef(false);

  // 浏览器抽屉：点击文件后右侧弹出，复用 BrowserDrawer
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserHref, setBrowserHref] = useState<string | null>(null);
  const [browserSeq, setBrowserSeq] = useState(0);

  const wsId = selectedWs?.id ?? null;
  const { data: files, isLoading: filesLoading } = useQuery({
    queryKey: ['ws-mgr-files', wsId],
    queryFn: () => wsId ? terminal.listWsFiles(wsId) : Promise.resolve([]),
    enabled: !!wsId,
  });
  const { data: folders } = useQuery({
    queryKey: ['ws-mgr-folders', wsId],
    queryFn: () => wsId ? terminal.listWsFolders(wsId) : Promise.resolve([]),
    enabled: !!wsId,
  });

  // 用户主动切换工作空间时回到根目录；首次深链接保留 path。
  useEffect(() => {
    if (previousWsRef.current && previousWsRef.current !== wsId) setCwd([]);
    previousWsRef.current = wsId;
    setSearch(''); setSelectedKeys(new Set());
  }, [wsId]);
  useEffect(() => { setSelectedKeys(new Set()); }, [cwd, search]);
  useEffect(() => {
    if (!wsId) return;
    const next = new URLSearchParams(urlParams);
    next.set('view', 'workspace');
    next.set('workspace', wsId);
    if (cwd.length) next.set('path', cwd.join('/')); else next.delete('path');
    if (next.toString() !== urlParams.toString()) setUrlParams(next, { replace: true });
  }, [cwd, setUrlParams, urlParams, wsId]);

  // 无搜索时展示当前层直系子项；搜索时覆盖整个工作空间并保留完整路径。
  const { folderItems, fileItems } = useMemo(() => {
    const allFolderPaths = new Map<string, WorkspaceFolder | null>();
    const addFolderPath = (path: string, rec: WorkspaceFolder | null = null) => {
      if (!path) return;
      if (!allFolderPaths.has(path)) allFolderPaths.set(path, rec);
      else if (rec && !allFolderPaths.get(path)) allFolderPaths.set(path, rec);
    };
    for (const f of folders ?? []) {
      const parts = f.path.split('/');
      for (let i = 1; i <= parts.length; i++) addFolderPath(parts.slice(0, i).join('/'), i === parts.length ? f : null);
    }
    for (const f of files ?? []) {
      const parts = f.path.split('/').slice(0, -1);
      for (let i = 1; i <= parts.length; i++) addFolderPath(parts.slice(0, i).join('/'));
    }
    const cwdPath = cwd.join('/');
    const query = search.trim().toLocaleLowerCase();
    const folderItems = [...allFolderPaths.entries()].flatMap(([path, record]) => {
      const parent = path.split('/').slice(0, -1).join('/');
      if (query ? !path.toLocaleLowerCase().includes(query) : parent !== cwdPath) return [];
      const technicalSegment = path.split('/').pop() || path;
      const related = (files ?? []).find((file) => file.path.startsWith(`${path}/`));
      const name = /^[0-9a-f-]{36}$/i.test(technicalSegment)
        ? (related?.presentation.source_task_title || '任务产物')
        : technicalSegment;
      return [{ name, path, record }];
    });
    const fileItems = (files ?? []).flatMap((file) => {
      const parent = file.path.split('/').slice(0, -1).join('/');
      const displayName = workspaceDisplayName(file);
      if (query ? !`${file.path} ${displayName}`.toLocaleLowerCase().includes(query) : parent !== cwdPath) return [];
      return [{ file, name: displayName, path: file.path }];
    });
    const compare = (a: { name: string; path: string; record?: WorkspaceFolder | null; file?: WorkspaceFileListItem }, b: typeof a) => {
      if (sortBy === 'time') return new Date(b.file?.updated_at ?? b.record?.updated_at ?? 0).getTime() - new Date(a.file?.updated_at ?? a.record?.updated_at ?? 0).getTime();
      if (sortBy === 'size') return (b.file?.size ?? 0) - (a.file?.size ?? 0) || a.name.localeCompare(b.name);
      if (sortBy === 'type') return fileType(a.path).localeCompare(fileType(b.path)) || a.name.localeCompare(b.name);
      return a.name.localeCompare(b.name);
    };
    folderItems.sort(compare);
    fileItems.sort(compare);
    return { folderItems, fileItems };
  }, [files, folders, cwd, search, sortBy]);

  const resultKeys = useMemo(() => [
    ...folderItems.map((item) => `d:${item.path}`),
    ...fileItems.map((item) => `f:${item.file.id}`),
  ], [folderItems, fileItems]);
  const toggleSelected = (key: string) => setSelectedKeys((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key); else next.add(key);
    return next;
  });

  const pointerInFileArea = (event: { clientX: number; clientY: number }) => {
    const area = fileAreaRef.current;
    if (!area) return null;
    const bounds = area.getBoundingClientRect();
    return {
      x: event.clientX - bounds.left + area.scrollLeft,
      y: event.clientY - bounds.top + area.scrollTop,
      bounds,
    };
  };

  const beginMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!selecting || event.button !== 0) return;
    const target = event.target as HTMLElement;
    if (target.closest('[data-workspace-item], button, input, [role="menu"]')) return;
    const point = pointerInFileArea(event);
    const area = fileAreaRef.current;
    if (!point || !area) return;
    const baseSelection = event.ctrlKey || event.metaKey || event.shiftKey
      ? new Set(selectedKeys)
      : new Set<string>();
    dragSelectionRef.current = {
      pointerId: event.pointerId,
      startX: point.x,
      startY: point.y,
      baseSelection,
    };
    setSelectedKeys(baseSelection);
    setMarquee({ left: point.x, top: point.y, width: 0, height: 0 });
    area.setPointerCapture(event.pointerId);
    event.preventDefault();
  };

  const updateMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragSelectionRef.current;
    const area = fileAreaRef.current;
    const point = pointerInFileArea(event);
    if (!drag || drag.pointerId !== event.pointerId || !area || !point) return;
    const box = {
      left: Math.min(drag.startX, point.x),
      top: Math.min(drag.startY, point.y),
      width: Math.abs(point.x - drag.startX),
      height: Math.abs(point.y - drag.startY),
    };
    const next = new Set(drag.baseSelection);
    area.querySelectorAll<HTMLElement>('[data-workspace-key]').forEach((item) => {
      const itemBounds = item.getBoundingClientRect();
      const itemBox = {
        left: itemBounds.left - point.bounds.left + area.scrollLeft,
        top: itemBounds.top - point.bounds.top + area.scrollTop,
        right: itemBounds.right - point.bounds.left + area.scrollLeft,
        bottom: itemBounds.bottom - point.bounds.top + area.scrollTop,
      };
      const intersects = box.left < itemBox.right
        && box.left + box.width > itemBox.left
        && box.top < itemBox.bottom
        && box.top + box.height > itemBox.top;
      if (intersects) next.add(item.dataset.workspaceKey!);
    });
    setMarquee(box);
    setSelectedKeys(next);
    event.preventDefault();
  };

  const endMarqueeSelection = (event: React.PointerEvent<HTMLDivElement>) => {
    const drag = dragSelectionRef.current;
    const area = fileAreaRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    dragSelectionRef.current = null;
    setMarquee(null);
    if (area?.hasPointerCapture(event.pointerId)) area.releasePointerCapture(event.pointerId);
    event.preventDefault();
  };
  const { data: trash = [], isLoading: trashLoading } = useQuery({
    queryKey: ['ws-mgr-trash', wsId], queryFn: () => terminal.listWsTrash(wsId!),
    enabled: !!wsId && trashOpen && canManage,
  });
  const { data: auditEvents = [], isLoading: auditLoading } = useQuery({
    queryKey: ['ws-mgr-audit', wsId], queryFn: () => terminal.listWsAudit(wsId!),
    enabled: !!wsId && auditOpen && canManage,
  });
  const { data: versions = [], isLoading: versionsLoading } = useQuery({
    queryKey: ['ws-mgr-versions', versionFile?.id], queryFn: () => terminal.listWsFileVersions(versionFile!.id),
    enabled: !!versionFile,
  });

  const createFolder = useMutation({
    mutationFn: (name: string) => {
      if (!wsId) return Promise.reject(new Error('no ws'));
      return terminal.createWsFolder(wsId, { path: [...cwd, name].join('/') });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      setFolderModalOpen(false); setFolderName('');
      message.success('文件夹已创建');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '创建失败'),
  });

  const delFolder = useMutation({
    mutationFn: (id: string) => terminal.deleteWsFolder(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      message.success('文件夹及其内容已删除');
    },
    onError: () => message.error('删除失败'),
  });

  const delFolderPath = useMutation({
    mutationFn: (path: string) => {
      if (!wsId) return Promise.reject(new Error('no ws'));
      return terminal.deleteWsFolderPath(wsId, path);
    },
    onSuccess: (result, path) => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      if (cwd.join('/') === path) setCwd((current) => current.slice(0, -1));
      message.success(`文件夹已删除（${result.files} 个文件，${result.folders} 个显式文件夹）`);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '删除文件夹失败'),
  });

  const uploadQueue = useWorkspaceUploadQueue<WorkspaceFile>({
    upload: (request, options) => terminal.uploadWsFile(
      request.workspaceId, request.file, request.path, options,
    ),
    onSuccess: (file, request) => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      message.success(file.parse_status === 'ready'
        ? `${request.file.name} 已上传，可使用`
        : `${request.file.name} 已上传，正在后台解析`);
    },
    onError: (error, request) => {
      message.error(`${request.file.name}：${error instanceof ApiError ? error.message : '上传失败'}`);
    },
  });

  const reparseFile = async (fileId: string) => {
    const updated = await terminal.reparseWsFile(fileId);
    await qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
    if (updated.parse_status === 'ready') message.success('文件解析完成');
    else if (updated.parse_status === 'queued' || updated.parse_status === 'processing') message.info('已加入解析队列');
    else message.warning(updated.parse_error || '文件仍无法解析');
  };

  const delFile = useMutation({
    mutationFn: (id: string) => terminal.deleteWsFile(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['ws-mgr-files'] }); message.success('文件已删除'); },
    onError: () => message.error('删除失败'),
  });

  const restoreTrash = useMutation({
    mutationFn: (fileId: string) => terminal.restoreWsTrash(wsId!, fileId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-trash'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      message.success('文件已从回收站恢复');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '恢复失败'),
  });

  const restoreVersion = useMutation({
    mutationFn: (versionId: string) => terminal.restoreWsFileVersion(versionFile!.id, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-versions'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      message.success('已恢复为一个新的当前版本');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '版本恢复失败'),
  });

  const publishMutation = useMutation({
    mutationFn: () => terminal.publishWsFile(publishFile!.id, publishTarget!),
    onSuccess: () => {
      setPublishFile(null); setPublishTarget(undefined);
      message.success('已发布到目标工作空间，个人原件仍保留');
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '发布失败'),
  });

  const shareFile = async (file: WorkspaceFileListItem) => {
    try {
      const share = await terminal.createWsShare(file.id);
      await navigator.clipboard.writeText(share.url);
      message.success('7 天有效分享链接已复制');
    } catch (e) {
      message.error(e instanceof ApiError ? e.message : '创建分享链接失败');
    }
  };

  const bulkDelete = useMutation({
    mutationFn: () => {
      if (!wsId) return Promise.reject(new Error('no ws'));
      return terminal.bulkDeleteWsItems(wsId, {
        file_ids: [...selectedKeys].filter((key) => key.startsWith('f:')).map((key) => key.slice(2)),
        folder_paths: [...selectedKeys].filter((key) => key.startsWith('d:')).map((key) => key.slice(2)),
      });
    },
    onSuccess: (result) => {
      qc.invalidateQueries({ queryKey: ['ws-mgr-folders'] });
      qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
      setSelectedKeys(new Set());
      message.success(`已删除 ${result.deleted_files} 个文件、${result.deleted_folders} 个显式文件夹`);
    },
    onError: (e: unknown) => message.error(e instanceof ApiError ? e.message : '批量删除失败'),
  });

  // 删除确认弹窗：不再用悬浮 Popconfirm，改为界面正中的模态框（字体与终端一致）。
  const [confirm, setConfirm] = useState<{
    kind: 'folder' | 'folderPath' | 'file' | 'bulk'; id: string; title: string; desc?: string;
  } | null>(null);
  const confirmLoading = confirm?.kind === 'folder'
    ? delFolder.isPending
    : confirm?.kind === 'folderPath'
      ? delFolderPath.isPending
      : confirm?.kind === 'file' ? delFile.isPending : confirm?.kind === 'bulk' ? bulkDelete.isPending : false;
  const confirmOk = () => {
    if (!confirm) return;
    if (confirm.kind === 'folder') delFolder.mutate(confirm.id);
    else if (confirm.kind === 'folderPath') delFolderPath.mutate(confirm.id);
    else if (confirm.kind === 'file') delFile.mutate(confirm.id);
    else bulkDelete.mutate();
    setConfirm(null);
  };

  // 把任意 href（http URL 或当前工作空间文件路径）解析为浏览器抽屉可渲染的 Source。
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    // react-markdown 会把含非 ASCII 的链接目标 percent-encode，工作空间路径需先解码再匹配
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    if (!wsId) return { kind: 'unsupported', href, note: '未选择工作空间' };
    let list: WorkspaceFileListItem[];
    try { list = await terminal.listWsFiles(wsId); }
    catch { return { kind: 'unsupported', href, note: '工作空间文件读取失败' }; }
    const f = list.find((x) => x.path === href || x.path.endsWith('/' + href) || href.endsWith(x.path));
    if (!f) return { kind: 'unsupported', href, note: `未找到该文件：${href}` };
    try { return classifyFile(await terminal.getWsFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [wsId]);

  const openFile = (path: string) => {
    setBrowserHref(path);
    setBrowserSeq((n) => n + 1);
    setBrowserOpen(true);
  };

  const submitFolder = () => {
    const name = folderName.trim();
    if (!name || name.includes('/')) { message.warning('请输入有效文件夹名（不含 /）'); return; }
    createFolder.mutate(name);
  };

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, fontFamily: WB_FONT, background: '#fff' }}>
      {/* 顶部标题栏 */}
      <div style={titleBarStyle}>
        <FolderOutlined style={{ color: WB.primary, fontSize: 16 }} />
        <span style={{ fontSize: 13, fontWeight: 600, color: '#1d1d1f' }}>工作空间</span>
        <Typography.Text style={{ fontSize: 12, color: '#86868b' }}>
          {selectedWs ? `${selectedWs.name}` : '选择左侧节点'}
        </Typography.Text>
      </div>

      {/* 2:8 主体 */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* 左栏：MacOS 风格工作空间树 */}
        <aside style={sidebarStyle}>
          <div style={sidebarHeaderStyle}>收藏</div>
          {treeData.length === 0 ? (
            <div style={{ padding: '8px 12px', color: '#86868b', fontSize: 12 }}>暂无可访问的工作空间</div>
          ) : (
            <MacTree
              nodes={treeData}
              selectedKey={selectedWsId ? `ws:${selectedWsId}` : null}
              onSelect={(wsIdSel) => setSelectedWsId(wsIdSel)}
            />
          )}
        </aside>

        {/* 右栏：MacOS Finder 风格文件夹 / 文件浏览器 */}
        <section style={{ flex: 8, minWidth: 0, display: 'flex', flexDirection: 'column', background: '#fff' }}>
          {!selectedWs ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择左侧工作空间节点以管理其文件夹 / 文件" />
            </div>
          ) : (
            <>
              {/* 工具条 + Mac 路径栏 */}
              <div style={toolbarStyle}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: 1 }}>
                  <button
                    style={navBtnStyle(cwd.length === 0)}
                    disabled={cwd.length === 0}
                    onClick={() => setCwd((c) => c.slice(0, -1))}
                    title="返回上一级"
                  ><ArrowUpOutlined style={{ transform: 'rotate(-90deg)' }} /></button>
                  <div style={pathBarStyle}>
                    <span className="wb-path-seg" onClick={() => setCwd([])} style={pathSegStyle}>
                      <HomeOutlined style={{ fontSize: 12, marginRight: 4 }} />{selectedWs.name}
                    </span>
                    {cwd.map((seg, i) => (
                      <span key={i} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        <RightOutlined style={{ fontSize: 9, color: '#b0b0b5', margin: '0 2px' }} />
                        <span className="wb-path-seg" onClick={() => setCwd((c) => c.slice(0, i + 1))} style={pathSegStyle}>
                          {seg}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Input
                    allowClear
                    prefix={<SearchOutlined />}
                    placeholder="搜索整个工作空间"
                    value={search}
                    onChange={(event) => setSearch(event.target.value)}
                    style={{ width: 190, height: 28, fontSize: 12 }}
                  />
                  <Select
                    size="small"
                    value={sortBy}
                    onChange={setSortBy}
                    style={{ width: 94 }}
                    options={[
                      { value: 'name', label: '按名称' }, { value: 'time', label: '按时间' },
                      { value: 'type', label: '按类型' }, { value: 'size', label: '按大小' },
                    ]}
                  />
                  <button style={toolBtnStyle} title={viewMode === 'grid' ? '切换列表视图' : '切换网格视图'} onClick={() => setViewMode((mode) => mode === 'grid' ? 'list' : 'grid')}>
                    {viewMode === 'grid' ? <UnorderedListOutlined /> : <AppstoreOutlined />}
                  </button>
                  <button style={{ ...toolBtnStyle, color: selecting ? WB.primary : '#1d1d1f' }} onClick={() => { setSelecting((value) => !value); setSelectedKeys(new Set()); setMarquee(null); dragSelectionRef.current = null; }}>
                    <CheckSquareOutlined /> {selecting ? '退出多选' : '多选'}
                  </button>
                  {selecting && canManage && (
                    <>
                      <button style={toolBtnStyle} onClick={() => setSelectedKeys(new Set(resultKeys))}>全选结果</button>
                      <button
                        style={{ ...toolBtnStyle, color: '#dc2626' }}
                        disabled={!selectedKeys.size}
                        onClick={() => setConfirm({ kind: 'bulk', id: '', title: `删除选中的 ${selectedKeys.size} 项？`, desc: '文件夹会连同全部子文件夹和文件一起删除，此操作不可撤销。' })}
                      ><DeleteOutlined /> 批量删除</button>
                    </>
                  )}
                  {canManage && <button style={toolBtnStyle} onClick={() => setTrashOpen(true)}><RestOutlined /> 回收站</button>}
                  {canManage && <button style={toolBtnStyle} onClick={() => setAuditOpen(true)}><AuditOutlined /> 审计</button>}
                  {cwd.length > 0 && canManage && (
                    <button
                      style={{ ...toolBtnStyle, color: '#dc2626' }}
                      onClick={() => setConfirm({
                        kind: 'folderPath', id: cwd.join('/'),
                        title: `删除“${cwd[cwd.length - 1]}”文件夹？`,
                        desc: '将一并删除当前文件夹、全部子文件夹和其中所有文件；此操作不可撤销。',
                      })}
                    >
                      <DeleteOutlined style={{ fontSize: 13 }} /> 删除当前文件夹
                    </button>
                  )}
                  <button style={toolBtnStyle} disabled={!canCreate} onClick={() => { setFolderName(''); setFolderModalOpen(true); }}>
                    <FolderAddOutlined style={{ fontSize: 13 }} /> 新建文件夹
                  </button>
                  <WorkspaceUploadPicker
                    disabled={!canCreate}
                    onLimitExceeded={(count) => message.warning(`一次最多上传 5 个文件；已选择 ${count} 个，本次只加入前 5 个`)}
                    onSelect={(selected) => {
                      if (!canCreate) {
                        message.warning('当前工作空间为只读');
                        return;
                      }
                      if (!wsId) return;
                      const accepted = selected.filter((file) => {
                        if (file.size <= WORKSPACE_MAX_FILE_BYTES) return true;
                        message.warning(`${file.name} 超过 5GB 存储上限，未加入上传队列`);
                        return false;
                      });
                      uploadQueue.enqueue(accepted.map((file) => ({
                        workspaceId: wsId,
                        path: [...cwd, file.name].join('/'),
                        file,
                      })));
                    }}
                  >
                    <button style={toolBtnStyle} disabled={!canCreate}>
                      <UploadOutlined style={{ fontSize: 13 }} /> 上传文件（可多选）
                    </button>
                  </WorkspaceUploadPicker>
                  <Typography.Text
                    type="secondary"
                    title="支持 Word、Excel、PPT、PDF、Markdown 等常用文件；100MB 内可自动 AI 解析，较大文件仍可存储和下载"
                    style={{ fontSize: 11, whiteSpace: 'nowrap' }}
                  >
                    单次最多 5 个 · 单文件最大 5GB · AI 解析上限 100MB
                  </Typography.Text>
                  <WorkspaceUploadQueueStatus
                    items={uploadQueue.items}
                    activeCount={uploadQueue.activeCount}
                    completedCount={uploadQueue.completedCount}
                    failedCount={uploadQueue.failedCount}
                    overallProgress={uploadQueue.overallProgress}
                    onClearFinished={uploadQueue.clearFinished}
                  />
                </div>
              </div>

              {/* 文件网格 / 列表 */}
              <div
                ref={fileAreaRef}
                style={{ flex: 1, overflowY: 'auto', padding: '18px 20px', position: 'relative', userSelect: selecting ? 'none' : undefined, touchAction: selecting ? 'none' : undefined }}
                className="wb-scroll-hide"
                onPointerDown={beginMarqueeSelection}
                onPointerMove={updateMarqueeSelection}
                onPointerUp={endMarqueeSelection}
                onPointerCancel={endMarqueeSelection}
              >
                {selecting && marquee && <div aria-hidden style={marqueeStyle(marquee)} />}
                {filesLoading ? (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: 48 }}><Spin /></div>
                ) : (folderItems.length === 0 && fileItems.length === 0) ? (
                  <div style={{ textAlign: 'center', color: '#86868b', fontSize: 13, marginTop: 48 }}>
                    此处暂无文件夹 / 文件
                  </div>
                ) : (
                  <div style={viewMode === 'grid' ? { display: 'flex', flexWrap: 'wrap', gap: 4 } : { display: 'flex', flexDirection: 'column', gap: 2 }}>
                    {folderItems.map((it) => {
                      const key = `d:${it.path}`;
                      const isHover = hovered === key;
                      const isActive = isHover || focused === key;
                      const showActions = viewMode === 'list' || isActive;
                      const selected = selectedKeys.has(key);
                      return (
                        <div
                          key={key}
                          data-workspace-item
                          data-workspace-key={key}
                          role="button"
                          tabIndex={0}
                          aria-label={`打开文件夹 ${it.name}`}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          onFocus={() => setFocused(key)}
                          onBlur={(event) => {
                            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(null);
                          }}
                          onClick={() => selecting ? toggleSelected(key) : (setCwd(it.path.split('/')), setSearch(''))}
                          onKeyDown={(event) => {
                            if (event.key !== 'Enter' && event.key !== ' ') return;
                            event.preventDefault();
                            selecting ? toggleSelected(key) : (setCwd(it.path.split('/')), setSearch(''));
                          }}
                          style={viewMode === 'grid' ? { ...iconCardStyle(isActive), background: selected ? '#e8eafe' : (isActive ? '#f0f1f4' : 'transparent') } : listRowStyle(selected || isActive)}
                        >
                          {selecting && <Checkbox checked={selected} onClick={(event) => event.stopPropagation()} onChange={() => toggleSelected(key)} style={viewMode === 'grid' ? { position: 'absolute', top: 5, left: 6 } : undefined} />}
                          <div style={viewMode === 'grid' ? { position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92, cursor: 'pointer' } : { display: 'contents' }}>
                            <FolderOutlined style={{ fontSize: viewMode === 'grid' ? 42 : 22, color: WB.macFolder }} />
                            <div style={viewMode === 'grid' ? iconNameStyle : listNameStyle} title={it.name}>{it.name}</div>
                            {viewMode === 'grid' && !!search.trim() && <div style={{ ...iconNameStyle, fontSize: 9, color: '#9ca3af', marginTop: 2 }} title={it.name}>{it.name}</div>}
                            {viewMode === 'list' && <><span style={listMetaStyle}>文件夹</span><span style={listMetaStyle}>{it.record?.updated_at ? new Date(it.record.updated_at).toLocaleString() : '路径推导'}</span><span style={listPathStyle}>{it.name}</span></>}
                            {!selecting && canManage && (
                              <Dropdown
                                trigger={['click']}
                                placement="bottomRight"
                                menu={{
                                  items: [{ key: 'delete', label: '删除文件夹', icon: <DeleteOutlined />, danger: true }],
                                  onClick: ({ domEvent }) => {
                                    domEvent.stopPropagation();
                                    setConfirm({ kind: it.record ? 'folder' : 'folderPath', id: it.record ? it.record.id : it.path, title: '删除该文件夹？', desc: '将一并删除其下所有子文件夹与文件' });
                                  },
                                }}
                              >
                                <button
                                  aria-label={`${it.name} 的更多操作`}
                                  title="更多操作"
                                  style={moreActionBtnStyle(viewMode, showActions)}
                                  onClick={(event) => event.stopPropagation()}
                                ><MoreOutlined /></button>
                              </Dropdown>
                            )}
                          </div>
                        </div>
                      );
                    })}
                    {fileItems.map((it) => {
                      const key = `f:${it.file.id}`;
                      const isHover = hovered === key;
                      const isActive = isHover || focused === key;
                      const showActions = viewMode === 'list' || isActive;
                      const selected = selectedKeys.has(key);
                      return (
                        <div
                          key={key}
                          data-workspace-item
                          data-workspace-key={key}
                          role="button"
                          tabIndex={0}
                          aria-label={`打开文件 ${it.name}`}
                          onMouseEnter={() => setHovered(key)}
                          onMouseLeave={() => setHovered(null)}
                          onFocus={() => setFocused(key)}
                          onBlur={(event) => {
                            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setFocused(null);
                          }}
                          onClick={() => selecting ? toggleSelected(key) : openFile(it.file.path)}
                          onKeyDown={(event) => {
                            if (event.key !== 'Enter' && event.key !== ' ') return;
                            event.preventDefault();
                            selecting ? toggleSelected(key) : openFile(it.file.path);
                          }}
                          style={viewMode === 'grid' ? { ...iconCardStyle(isActive), background: selected ? '#e8eafe' : (isActive ? '#f0f1f4' : 'transparent') } : listRowStyle(selected || isActive)}
                        >
                          {selecting && <Checkbox checked={selected} onClick={(event) => event.stopPropagation()} onChange={() => toggleSelected(key)} style={viewMode === 'grid' ? { position: 'absolute', top: 5, left: 6 } : undefined} />}
                          <div style={viewMode === 'grid' ? { position: 'relative', display: 'flex', flexDirection: 'column', alignItems: 'center', width: 92 } : { display: 'contents' }}>
                            <FileTextOutlined style={{ fontSize: viewMode === 'grid' ? 42 : 22, color: WB.macFile }} />
                            <div style={viewMode === 'grid' ? iconNameStyle : listNameStyle} title={it.name}>{it.name}</div>
                            {viewMode === 'grid' && !!search.trim() && <div style={{ ...iconNameStyle, fontSize: 9, color: '#9ca3af', marginTop: 2 }} title={workspaceVisiblePath(it.file)}>{workspaceVisiblePath(it.file)}</div>}
                            {viewMode === 'grid' ? (
                              <span style={{ fontSize: 10, color: '#aeaeb2', marginTop: 1 }}>{formatBytes(it.file.size)}</span>
                            ) : (
                              <><span style={listMetaStyle}>{fileType(it.file.path)} · {formatBytes(it.file.size)}</span><span style={listMetaStyle}>{new Date(it.file.updated_at).toLocaleString()}</span><span style={listMetaStyle}>{PARSE_LABEL[it.file.parse_status] ?? it.file.parse_status}</span><span style={listPathStyle}>{workspaceVisiblePath(it.file)}</span></>
                            )}
                            {!selecting && (
                              <Dropdown
                                trigger={['click']}
                                placement="bottomRight"
                                menu={{
                                  items: [
                                    { key: 'open', label: '查看文件', icon: <EyeOutlined /> },
                                    ...(canManage ? [
                                      { key: 'versions', label: '版本历史', icon: <HistoryOutlined /> },
                                      { key: 'share', label: '创建限时分享', icon: <ShareAltOutlined /> },
                                    ] : []),
                                    ...(selectedWs.capabilities?.publish ? [{ key: 'publish', label: '发布到部门或团队', icon: <SendOutlined /> }] : []),
                                    ...(canManage ? [{ key: 'delete', label: '移至回收站', icon: <DeleteOutlined />, danger: true }] : []),
                                  ],
                                  onClick: ({ key: action, domEvent }) => {
                                    domEvent.stopPropagation();
                                    if (action === 'open') openFile(it.file.path);
                                    else if (action === 'versions') setVersionFile(it.file);
                                    else if (action === 'share') void shareFile(it.file);
                                    else if (action === 'publish') setPublishFile(it.file);
                                    else if (action === 'delete') setConfirm({ kind: 'file', id: it.file.id, title: '将该文件移至回收站？', desc: '文件将在回收站保留 30 天，可由负责人恢复。' });
                                  },
                                }}
                              >
                                <button
                                  aria-label={`${it.name} 的更多操作`}
                                  title="更多操作"
                                  style={moreActionBtnStyle(viewMode, showActions)}
                                  onClick={(event) => event.stopPropagation()}
                                ><MoreOutlined /></button>
                              </Dropdown>
                            )}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
                {folderItems.length === 0 && fileItems.length === 0 && !filesLoading && (
                  <Typography.Text style={{ display: 'block', marginTop: 16, fontSize: 11, color: '#aeaeb2', textAlign: 'center' }}>
                    点击文件夹进入 · 点击文件查看 · 同名上传将建立不可变新版本
                  </Typography.Text>
                )}
              </div>
            </>
          )}
        </section>
      </div>

      {/* 查看文件：复用任务消息区右侧浏览器抽屉 */}
      <BrowserDrawer
        key={browserSeq}
        open={browserOpen}
        initialHref={browserHref}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        onReparse={reparseFile}
        loadOriginalPreview={terminal.getWsFileOriginalPreview}
        loadOriginalPreviewSource={terminal.getWsFileOriginalPreviewSource}
        loadPdfPreviewInfo={terminal.getWsFilePdfPreviewInfo}
        loadPdfPreviewPage={terminal.getWsFilePdfPreviewPage}
        loadOriginalFile={terminal.downloadWsFile}
        loadDownloadTicket={terminal.getWsFileDownloadTicket}
        loadPreviewSession={terminal.createWsFilePreviewSession}
        refreshPreviewSession={terminal.refreshWsFilePreviewSession}
        startFallbackPreview={terminal.startWsFileFallbackPreview}
        getFallbackPreview={terminal.getWsFileFallbackPreview}
      />

      {/* 新建文件夹 */}
      <NewFolderModal
        open={folderModalOpen}
        value={folderName}
        setValue={setFolderName}
        cwd={cwd}
        composingRef={composingRef}
        loading={createFolder.isPending}
        onCancel={() => { setFolderModalOpen(false); setFolderName(''); }}
        onOk={submitFolder}
      />

      {/* 删除确认：界面正中模态框（字体随根容器继承终端 WB_FONT） */}
      <ConfirmModal
        open={!!confirm}
        title={confirm?.title ?? ''}
        desc={confirm?.desc}
        loading={confirmLoading}
        onCancel={() => setConfirm(null)}
        onOk={confirmOk}
      />

      <Modal title="回收站（保留 30 天）" open={trashOpen} footer={null} onCancel={() => setTrashOpen(false)} width={720}>
        <List loading={trashLoading} dataSource={trash} locale={{ emptyText: '回收站为空' }} renderItem={(file) => (
          <List.Item actions={[<a key="restore" onClick={() => restoreTrash.mutate(file.id)}>恢复</a>]}>
            <List.Item.Meta title={workspaceDisplayName(file)} description={[workspaceSourceLabel(file), formatBytes(file.size)].filter(Boolean).join(' · ')} />
          </List.Item>
        )} />
      </Modal>

      <Modal title={`版本历史${versionFile ? ` · ${workspaceDisplayName(versionFile)}` : ''}`} open={!!versionFile} footer={null} onCancel={() => setVersionFile(null)} width={720}>
        <List loading={versionsLoading} dataSource={versions} locale={{ emptyText: '暂无版本' }} renderItem={(version, index) => (
          <List.Item actions={index === 0 ? [] : [<a key="restore" onClick={() => restoreVersion.mutate(version.id)}>恢复此版本</a>]}>
            <List.Item.Meta title={`版本 ${version.version_no}${index === 0 ? '（当前）' : ''}`} description={`${formatBytes(version.size)} · ${new Date(version.created_at).toLocaleString()} · ${PARSE_LABEL[version.parse_status] ?? version.parse_status}`} />
          </List.Item>
        )} />
      </Modal>

      <Modal title="发布文件" open={!!publishFile} confirmLoading={publishMutation.isPending} okButtonProps={{ disabled: !publishTarget }} onCancel={() => { setPublishFile(null); setPublishTarget(undefined); }} onOk={() => publishMutation.mutate()}>
        <Typography.Paragraph>发布会在目标工作空间建立一份受版本管理的文件，个人原件不会删除。</Typography.Paragraph>
        <Select style={{ width: '100%' }} placeholder="选择本人所属部门或团队" value={publishTarget} onChange={setPublishTarget} options={workspaces.filter((workspace) => workspace.id !== selectedWsId && workspace.capabilities?.create && (workspace.scope_type === 'department' || workspace.scope_type === 'team')).map((workspace) => ({ value: workspace.id, label: `${SCOPE_LABEL[workspace.scope_type]} · ${workspace.name}` }))} />
      </Modal>

      <Modal title="工作空间审计" open={auditOpen} footer={null} onCancel={() => setAuditOpen(false)} width={760}>
        <List loading={auditLoading} dataSource={auditEvents} locale={{ emptyText: '暂无审计事件' }} renderItem={(event) => (
          <List.Item>
            <List.Item.Meta
              title={auditTitle(event)}
              description={auditSummary(event)}
            />
          </List.Item>
        )} />
      </Modal>
    </div>
  );
}

// ── MacOS 风格工作空间树（Finder 侧栏） ──────────────────────────────────

function MacTree({ nodes, selectedKey, onSelect }: {
  nodes: TreeNode[];
  selectedKey: string | null;
  onSelect: (wsId: string) => void;
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
          onClick={() => onSelect(node.wsId)}
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

// ── 新建文件夹弹窗（MacOS 风格） ─────────────────────────────────────────

function NewFolderModal(props: {
  open: boolean; value: string; setValue: (v: string) => void; cwd: string[];
  composingRef: { current: boolean }; loading: boolean;
  onCancel: () => void; onOk: () => void;
}) {
  const { open, value, setValue, cwd, composingRef, loading, onCancel, onOk } = props;
  if (!open) return null;
  return (
    <div style={modalOverlayStyle} onClick={onCancel}>
      <div style={modalCardStyle} onClick={(e) => e.stopPropagation()}>
        <div style={{ padding: '14px 18px', fontSize: 13, fontWeight: 600, color: '#1d1d1f', borderBottom: `1px solid ${WB.border}` }}>新建文件夹</div>
        <div style={{ padding: '18px' }}>
          <Input
            autoFocus
            placeholder="文件夹名"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onCompositionStart={() => { composingRef.current = true; }}
            onCompositionEnd={(e) => { composingRef.current = false; setValue((e.target as HTMLInputElement).value); }}
            onPressEnter={(e) => {
              if (composingRef.current || (e.nativeEvent as KeyboardEvent & { isComposing?: boolean }).isComposing) return;
              onOk();
            }}
            style={{ fontSize: 13 }}
            suffix={value ? <Typography.Text style={{ fontSize: 11, color: '#86868b' }}>→ {[...cwd, value].join('/')}</Typography.Text> : null}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 18px 16px' }}>
          <button style={toolBtnStyle} onClick={onCancel}>取消</button>
          <button style={{ ...toolBtnStyle, background: WB.primary, color: '#fff', border: 'none' }} disabled={loading} onClick={onOk}>
            {loading ? '创建中…' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 删除确认弹窗改用共享 ConfirmModal（见 ./ConfirmModal） ──────────────

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

const pathBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', flex: 1, minWidth: 0, overflow: 'hidden',
  background: '#eef0f3', borderRadius: 6, padding: '4px 10px', height: 28,
  fontSize: 12, color: '#1d1d1f',
};

const pathSegStyle: CSSProperties = {
  cursor: 'pointer', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  display: 'inline-flex', alignItems: 'center', borderRadius: 4, padding: '0 2px',
};

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

const iconCardStyle = (hover: boolean): CSSProperties => ({
  width: 108, padding: '10px 6px 8px', borderRadius: 8, cursor: 'pointer',
  display: 'flex', alignItems: 'flex-start', justifyContent: 'center',
  border: '1px solid transparent', transition: 'background .12s',
  background: hover ? '#f0f1f4' : 'transparent', position: 'relative',
});

const listRowStyle = (active: boolean): CSSProperties => ({
  display: 'grid', gridTemplateColumns: '24px minmax(180px, 1.4fr) 120px 150px 110px minmax(160px, 1fr) auto',
  alignItems: 'center', gap: 10, minHeight: 40, padding: '5px 8px', borderRadius: 6,
  background: active ? '#f0f1f4' : 'transparent', cursor: 'pointer', fontSize: 12,
});

const listNameStyle: CSSProperties = {
  minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: '#1d1d1f',
};

const listMetaStyle: CSSProperties = {
  color: '#6b7280', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
};

const listPathStyle: CSSProperties = {
  ...listMetaStyle, color: '#9ca3af', direction: 'rtl', textAlign: 'left',
};

const iconNameStyle: CSSProperties = {
  marginTop: 6, fontSize: 12, color: '#1d1d1f', textAlign: 'center',
  overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box',
  WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', width: '100%', lineHeight: 1.3,
};

const moreActionBtnStyle = (viewMode: 'grid' | 'list', visible: boolean): CSSProperties => ({
  width: 24, height: 24, borderRadius: 6, border: 'none', cursor: 'pointer',
  display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11,
  background: 'rgba(255,255,255,0.9)', boxShadow: '0 1px 3px rgba(0,0,0,0.18)',
  color: '#1d1d1f', opacity: visible ? 1 : 0, pointerEvents: visible ? 'auto' : 'none',
  transition: 'opacity .12s ease, background .12s ease',
  ...(viewMode === 'grid' ? { position: 'absolute', top: -6, right: -6, zIndex: 1 } : {}),
});

const marqueeStyle = (box: { left: number; top: number; width: number; height: number }): CSSProperties => ({
  position: 'absolute',
  left: box.left,
  top: box.top,
  width: box.width,
  height: box.height,
  zIndex: 2,
  boxSizing: 'border-box',
  border: `1px solid ${WB.primary}`,
  borderRadius: 4,
  background: 'rgba(99, 102, 241, 0.12)',
  pointerEvents: 'none',
});

const modalOverlayStyle: CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', zIndex: 1000,
  display: 'flex', alignItems: 'center', justifyContent: 'center',
};

const modalCardStyle: CSSProperties = {
  width: 380, background: '#fff', borderRadius: 12,
  boxShadow: '0 12px 32px rgba(0,0,0,0.18)', overflow: 'hidden',
};
