import { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import OfficeFilePreview from '../../src/components/files/OfficeFilePreview';
import { FinderPromptModal } from '../../src/components/finder/primitives';
import BrowserDrawer, { type Source } from '../../src/pages/terminal/BrowserDrawer';
import type { WorkspaceFile } from '../../src/api/client';

const now = new Date().toISOString();

function workspaceFile(path: string, overrides: Partial<WorkspaceFile> = {}): WorkspaceFile {
  return {
    id: `file-${path}`,
    workspace_id: 'workspace-regression',
    workspace_name: '测试工作空间',
    canonical_path: `测试工作空间:/${path}`,
    path,
    size: 128,
    content_hash: 'test-hash',
    content: '',
    metadata: {},
    extracted_text: null,
    parse_status: 'ready',
    parse_kind: null,
    parse_error: null,
    created_at: now,
    updated_at: now,
    current_version_id: 'version-1',
    capabilities: { read: true, create: true, update: true, delete: true },
    ...overrides,
  };
}

const unsupported = async (href: string): Promise<Source> => ({ kind: 'unsupported', href });

function ImeHarness() {
  const [value, setValue] = useState('');
  const [submitted, setSubmitted] = useState('');
  const composingRef = useRef(false);
  return (
    <>
      <div data-testid="ime-value">{value}</div>
      <div data-testid="ime-submitted">{submitted}</div>
      <FinderPromptModal
        open
        title="新建文件夹"
        placeholder="文件夹名"
        value={value}
        setValue={setValue}
        composingRef={composingRef}
        onCancel={() => undefined}
        onOk={() => setSubmitted(value)}
      />
    </>
  );
}

function DraftHarness() {
  const file = workspaceFile('说明.md', { content: '原始内容' });
  return (
    <BrowserDrawer
      open
      initialFileId={file.id}
      onClose={() => undefined}
      resolveHref={unsupported}
      loadFileById={async () => file}
      saveTextFile={async (_fileId, data) => ({ ...file, content: data.content, current_version_id: 'version-2' })}
    />
  );
}

function HtmlSecurityHarness() {
  const file = workspaceFile('untrusted.html', {
    content: '<script>localStorage.setItem("workspace-html-script", "executed")</script>\n<img src="x" onerror="localStorage.setItem(\'workspace-html-onerror\', \'executed\')">',
  });
  return (
    <BrowserDrawer
      open
      initialFileId={file.id}
      onClose={() => undefined}
      resolveHref={unsupported}
      loadFileById={async () => file}
    />
  );
}

function SpreadsheetHarness() {
  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      <OfficeFilePreview
        url="/__workspace-file-ui.xlsx"
        filename="旧文件.xlsx"
        extension="xlsx"
        size={16 * 1024}
        onDownload={() => undefined}
      />
    </div>
  );
}

const selectedCase = new URLSearchParams(window.location.search).get('case');
const element = selectedCase === 'ime'
  ? <ImeHarness />
  : selectedCase === 'draft'
    ? <DraftHarness />
    : selectedCase === 'html-security'
      ? <HtmlSecurityHarness />
      : <SpreadsheetHarness />;

createRoot(document.getElementById('root')!).render(element);
