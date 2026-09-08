import { useCallback, useEffect, useState } from 'react';
import { Empty, Tag, Tree, Typography } from 'antd';
import { FileTextOutlined } from '@ant-design/icons';
import { useQueryClient } from '@tanstack/react-query';
import {
  terminal, type TaskConfig, type TerminalAgent, type TerminalMemoryItem,
  type TerminalResources, type WorkspaceFileListItem,
} from '../../api/client';
import BrowserDrawer, { classifyFile, classifyUrl, type Source } from './BrowserDrawer';
import { workspaceFileLabel } from '../../utils/workspaceFileLinks';

const BORDER_COLOR = '#E5E7EB';

// ── 右栏子面板 ──────────────────────────────────────────────────────────

export function ResourcePanel({ taskConfig, resources, agent }: {
  taskConfig: TaskConfig; resources?: TerminalResources; agent?: TerminalAgent;
}) {
  const ws = resources?.workspaces.find((w) => w.id === taskConfig.workspace_id);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <Typography.Text type="secondary">工作空间</Typography.Text>
        <div><Tag color={ws ? 'blue' : 'default'}>{ws ? ws.name : '未选择'}</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">智能体默认 Skill</Typography.Text>
        <div><Tag color="blue">默认推荐 {agent?.skill_ids.length ?? 0} · 用户可用 {resources?.skills.length ?? 0}</Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">智能体固定 RAG</Typography.Text>
        <div><Tag color={agent?.rag_collection_ids.length ? 'blue' : 'default'}>
          {agent ? `固定绑定 ${agent.rag_collection_ids.length}` : '通用智能体不加载 RAG'}
        </Tag></div>
      </div>
      <div>
        <Typography.Text type="secondary">长期记忆</Typography.Text>
        <div><Tag color="blue">按权限自动载入 4 级</Tag></div>
      </div>
    </div>
  );
}
export function FilePanel({ workspaceId, workspaceName }: { workspaceId: string | null; workspaceName?: string }) {
  const qc = useQueryClient();
  const [files, setFiles] = useState<WorkspaceFileListItem[]>([]);
  // 复用 BrowserDrawer 预览（与「工作空间管理」页同一组件，消除两处功能差异）
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserFileId, setBrowserFileId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) { setFiles([]); return; }
    try { setFiles(await terminal.listWsFiles(workspaceId)); } catch { setFiles([]); }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  // 解析文件路径为可渲染 Source（http 链接按扩展名，工作空间文件统一走 classifyFile）
  const resolveHref = useCallback(async (rawHref: string): Promise<Source> => {
    if (/^https?:\/\//i.test(rawHref)) return classifyUrl(rawHref);
    let href = rawHref;
    try { href = decodeURIComponent(rawHref); } catch { /* 非法转义，保留原值 */ }
    if (!workspaceId) return { kind: 'unsupported', href, note: '该任务未绑定工作空间' };
    let list: WorkspaceFileListItem[];
    try { list = await terminal.listWsFiles(workspaceId); }
    catch { return { kind: 'unsupported', href, note: '工作空间文件读取失败' }; }
    const exact = list.find((x) => x.path === href);
    const suffixMatches = exact ? [] : list.filter((x) => x.path.endsWith('/' + href) || href.endsWith('/' + x.path));
    const f = exact ?? (suffixMatches.length === 1 ? suffixMatches[0] : undefined);
    if (!f) return { kind: 'unsupported', href, note: `未找到该文件：${href}` };
    try { return classifyFile(await terminal.getWsFile(f.id)); }
    catch { return { kind: 'unsupported', href, note: '文件详情读取失败' }; }
  }, [workspaceId]);

  if (!workspaceId) return <Empty description="该任务未绑定工作空间" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <Typography.Text type="secondary">工作空间文件（点击预览，智能体可读写）</Typography.Text>
      <Tree
        treeData={files.map((f) => ({ key: f.id, title: workspaceFileLabel(f), icon: <FileTextOutlined /> }))}
        height={200}
        onSelect={(keys) => {
          const fileId = keys[0] as string | undefined;
          if (!fileId) return;
          setBrowserFileId(fileId);
          setBrowserOpen(true);
        }}
      />
      <BrowserDrawer
        open={browserOpen}
        initialFileId={browserFileId}
        onClose={() => setBrowserOpen(false)}
        resolveHref={resolveHref}
        loadFileById={terminal.getWsFile}
        loadFileVersionById={terminal.getWsFileVersion}
        fallbackWorkspaceName={workspaceName}
        saveTextFile={terminal.updateWsFile}
        listFileVersions={terminal.listWsFileVersions}
        restoreFileVersion={terminal.restoreWsFileVersion}
        onFileChanged={() => {
          void load();
          qc.invalidateQueries({ queryKey: ['terminal-all-ws-files'] });
          qc.invalidateQueries({ queryKey: ['ws-mgr-files'] });
        }}
        loadOriginalPreview={terminal.getWsFileOriginalPreview}
        loadOriginalPreviewSource={terminal.getWsFileOriginalPreviewSource}
        loadPdfPreviewInfo={terminal.getWsFilePdfPreviewInfo}
        loadPdfPreviewPage={terminal.getWsFilePdfPreviewPage}
        loadPreviewSession={terminal.createWsFilePreviewSession}
        refreshPreviewSession={terminal.refreshWsFilePreviewSession}
        startFallbackPreview={terminal.startWsFileFallbackPreview}
        getFallbackPreview={terminal.getWsFileFallbackPreview}
        startSpreadsheetPreview={terminal.startWsFileSpreadsheetPreview}
        getSpreadsheetPreview={terminal.getWsFileSpreadsheetPreview}
        getSpreadsheetPage={terminal.getWsFileSpreadsheetPage}
        loadDownloadTicket={terminal.getWsFileDownloadTicket}
        loadOriginalFile={terminal.downloadWsFile}
      />
    </div>
  );
}

export function MemoryPanel({ items }: { items: TerminalMemoryItem[] }) {
  const scopeColor: Record<string, string> = { organization: 'blue', department: 'cyan', role: 'green', user: 'purple' };
  if (items.length === 0) return <Empty description="暂无记忆" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  return (
    <div>
      {items.map((m, i) => (
        <div key={i} style={{ padding: '8px 0', borderBottom: `1px solid ${BORDER_COLOR}` }}>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 4 }}>
            <Tag color={scopeColor[m.scope_type] || 'default'}>{m.scope_type}</Tag>
            <Tag>{m.category}</Tag>
            {m.source === 'auto' && <Tag color="purple">智能体沉淀</Tag>}
          </div>
          <Typography.Text style={{ fontSize: 12 }}>{m.content}</Typography.Text>
        </div>
      ))}
    </div>
  );
}
