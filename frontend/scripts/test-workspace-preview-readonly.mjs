import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const root = new URL('../src/pages/', import.meta.url);
const drawer = readFileSync(new URL('terminal/BrowserDrawer.tsx', root), 'utf8');
for (const retired of ['saveTextFile', 'startTextEdit', 'editingText', 'textDraft', 'serializeCsvDocument', '保存为新版本']) {
  assert.ok(!drawer.includes(retired), `retired web editing remains: ${retired}`);
}
for (const retained of ['OriginalFilePreview', '版本历史', "'下载'", 'loadOriginalFile', 'loadDownloadTicket', 'loadFileVersionById']) {
  assert.ok(drawer.includes(retained), `preview/download capability missing: ${retained}`);
}
for (const path of ['agent/Workspaces.tsx', 'terminal/Terminal.tsx', 'terminal/TerminalPanels.tsx', 'terminal/WorkspaceManagerView.tsx']) {
  assert.ok(!readFileSync(new URL(path, root), 'utf8').includes('saveTextFile='), `${path} still supplies a web editor`);
}
console.log('PASS: shared admin/employee preview retains read/download/history, no web text editor');
const admin = readFileSync(new URL('agent/Workspaces.tsx', root), 'utf8');
assert.match(admin, /titleExtra=\{linkResolutionPending\s*\?/);
assert.match(admin, /setLinkResolutionPending\(false\)/);
console.log('PASS: administrator deep links resolve before default organization selection');
