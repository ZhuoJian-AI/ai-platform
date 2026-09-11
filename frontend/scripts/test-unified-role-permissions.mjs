import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';

const source = readFileSync(new URL('../src/pages/apps/EnterpriseAccessControl.tsx', import.meta.url), 'utf8');
const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
assert(!app.includes('/org/roles'));
assert(!existsSync(new URL('../src/pages/org/Roles.tsx', import.meta.url)));
assert(source.includes("label: '语音与平台能力'"));
assert(source.includes('roles.update(role.id'));
assert(source.includes('roles.delete(id)'));
// Execute the actual permission selection expressions used by the save handler.
const options = source.match(/const PLATFORM_PERMISSIONS = (\[[\s\S]*?\]);/)[1];
const predicate = new Function(`const PLATFORM_PERMISSIONS = ${options}; return code => PLATFORM_PERMISSIONS.some(item => item.value === code);`)();
const retained = source.match(/const retainedPermissionCodes = (role.permission_codes.filter\([\s\S]*?\));/)[1];
const merge = source.match(/roles.replacePermissions\(role.id, (Array.from\(new Set\(\[[\s\S]*?\]\)\))/)[1];
function save(codes, selected, workspace = []) {
  const role = { permission_codes: codes };
  const keep = new Function('role', 'isPlatformPermission', `const DEPARTMENT_READ_PREFIX='workspace.department.read:'; const DEPARTMENT_UPLOAD_PREFIX='workspace.department.upload:'; const ORGANIZATION_MANAGE_PERMISSION='workspace.organization.manage'; const ORGANIZATION_READ_PERMISSION='workspace.organization.read'; return ${retained};`)(role, predicate);
  return new Function('role', 'isPlatformPermission', 'retainedPermissionCodes', 'workspacePermissionCodes', 'inheritsAllWorkspaceAccess', 'platformPermissions', `return ${merge};`)(role, predicate, keep, workspace, codes.includes('*'), selected);
}
assert.deepEqual(save(['custom.read', 'multimodal.speech.use'], ['multimodal.audio.transcribe'], ['workspace.department.read:one']),
  ['custom.read', 'workspace.department.read:one', 'multimodal.audio.transcribe']);
assert.deepEqual(save(['*', 'multimodal.speech.use'], []), ['*', 'multimodal.speech.use']);
assert.deepEqual(save([], []), []);
assert.deepEqual(save(['multimodal.audio.transcribe'], []), []);
console.log('PASS: unified route, role controls, grant/revoke, wildcard and unrelated permission preservation');
