import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const read = (path) => readFile(resolve(path), 'utf8');
const [
  app,
  client,
  terminal,
  applications,
  applicationDetail,
  applicationView,
  uploadQueue,
  previewSession,
  workspaces,
  providers,
  pkgSource,
  nginxConfig,
] = await Promise.all([
  read('src/App.tsx'),
  read('src/api/client.ts'),
  read('src/pages/terminal/Terminal.tsx'),
  read('src/pages/apps/EnterpriseApplications.tsx'),
  read('src/pages/apps/EnterpriseApplicationDetail.tsx'),
  read('src/pages/terminal/EnterpriseApplicationView.tsx'),
  read('src/components/files/WorkspaceUploadQueue.tsx'),
  read('src/components/files/WorkspacePreviewSessionView.tsx'),
  read('src/pages/agent/Workspaces.tsx'),
  read('src/pages/LlmProviders.tsx'),
  read('package.json'),
  read('nginx.coolify.conf'),
]);

const runtimeSources = [client, terminal, applications, applicationDetail, applicationView, uploadQueue].join('\n');
assert.doesNotMatch(runtimeSources, /skills-pack\/export|exportSkillsPack|导出 Skills/);
assert.doesNotMatch(runtimeSources, /tool_endpoint|data_interface|tool_bindings|replaceToolBindings/);
assert.doesNotMatch(applicationView, /\bontology\b/i);
assert.doesNotMatch(client, /\bteam_id\b|office_edit_enabled/);
assert.doesNotMatch(uploadQueue, /WebOffice 协同编辑|workspace_file_active_edit_conflict/);
assert.doesNotMatch(applications, /七天|迁移观察|旧工具绑定/);
assert.doesNotMatch(providers, /openai_embeddings|embedding_dimensions|Embedding/);
assert.doesNotMatch(client, /\| 'embedding'|embedding_dimensions/);

assert.match(app, /<Route path="\/\*" element=\{<NotFoundPage \/>\} \/>/);
assert.match(app, /<Route path="\/:slug\/terminal\/\*" element=\{<NotFoundPage \/>\} \/>/);
assert.match(app, /<Route path="\/terminal\/\*" element=\{<NotFoundPage \/>\} \/>/);
assert.doesNotMatch(app, /<Route path="\/\*" element=\{<Navigate to="\/monitor\/router"/);
assert.doesNotMatch(app, /path:\s*['"]\/(?:connectors|data-interfaces|ontology|judge|teams|extensions|office-edit|mcp)/);
assert.doesNotMatch(nginxConfig, /mcp|well-known/);

assert.match(applicationDetail, /Manifest Action 能力/);
assert.match(applicationDetail, /actionsQuery\.data/);
assert.match(applications, /业务小助手仅使用已审核的 Manifest Action/);

// User-uploaded Skills are retired, while workspaces and read-only Office preview remain.
assert.equal(existsSync(resolve('src/pages/tools/Skills.tsx')), false);
assert.equal(existsSync(resolve('src/pages/agent/Rag.tsx')), false);
assert.equal(existsSync(resolve('src/pages/terminal/KnowledgeBaseView.tsx')), false);
assert.equal(existsSync(resolve('src/pages/terminal/SkillManagerView.tsx')), false);
assert.match(workspaces, /BrowserDrawer/);
assert.match(previewSession, /data-testid="weboffice-preview"/);

const pkg = JSON.parse(pkgSource);
assert.equal(pkg.dependencies?.playwright, undefined);
assert.equal(pkg.devDependencies?.playwright, '^1.61.1');

process.stdout.write('retired frontend cleanup tests passed\n');
