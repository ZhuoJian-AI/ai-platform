import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const files = {
  client: await readFile(resolve('src/api/client.ts'), 'utf8'),
  organizations: await readFile(resolve('src/pages/Organizations.tsx'), 'utf8'),
  profile: await readFile(resolve('src/pages/org/EnterpriseProfile.tsx'), 'utf8'),
  apiKeys: await readFile(resolve('src/pages/ApiKeys.tsx'), 'utf8'),
  monitor: await readFile(resolve('src/pages/monitor/RouterMonitor.tsx'), 'utf8'),
};

assert.match(files.client, /budget_cap_credits: number \| null/);
assert.match(files.client, /readonly budget_cap_usd: string \| null/);
assert.match(files.client, /interface BudgetScopeUsage/);
assert.match(files.client, /effective_remaining: BudgetScopeRemaining/);
assert.match(files.client, /scopes: BudgetScopeUsage\[\]/);
assert.match(files.organizations, /budget_cap_credits: values\.budget_cap_credits \?\? null/);
assert.match(files.profile, /name="budget_cap_credits"/);
assert.match(files.apiKeys, /budget_cap_credits: formData\.budget_cap_credits \?\? null/);
assert.match(files.monitor, /dataIndex: 'credits'/);
assert.match(files.monitor, /row\.direct_caps\.monthly_credits/);
assert.match(files.monitor, /retained_unknown_tokens/);
assert.match(files.monitor, /保守占用\/尚未回报/);
assert.match(files.monitor, /usage\?\.scopes \?\? \[\]/);
assert.match(files.monitor, /row\.effective_remaining\.monthly_tokens/);
assert.match(files.monitor, /row\.effective_remaining\.monthly_credits/);
assert.match(files.monitor, /企业 \/ 部门 \/ 团队 \/ API Key 四级额度/);
assert.match(files.monitor, /页面不自行推算/);
assert.match(files.monitor, /scopeType === 'organization' \? '无限' : '继承'/,
  'a null direct cap is unlimited only at organization scope and inherited below it');
assert.match(files.monitor, /function renderEffectiveRemaining[\s\S]*?<Tag>无限<\/Tag>/,
  'a null effective remaining value means the complete scope chain is unlimited');
assert.doesNotMatch(files.monitor, /Key 调用额度上限合计/);
assert.doesNotMatch(files.monitor, /r\.credits\s*\/\s*cap/);
assert.doesNotMatch(files.monitor, /effective_remaining\s*=|effectiveRemaining\s*=/,
  'frontend must consume server-computed effective remaining values');
assert.match(files.profile, /enterpriseScoped \? \{/,
  'enterprise administrators must submit profile fields without top-level quotas');
assert.match(files.profile, /disabled=\{enterpriseScoped\}/);
assert.match(files.organizations, /isOrgScoped\(\) && editTarget\.kind === 'org' \? profilePayload/);
assert.match(files.apiKeys, /失败不退；供应商重试或故障转移不重复扣/);

for (const [name, source] of Object.entries(files)) {
  assert.doesNotMatch(
    source,
    /<Form\.Item[^>]*name=["']budget_cap_usd["']/,
    `${name} must never expose the legacy USD field as an editable form value`,
  );
}

process.stdout.write('admin quota tests passed\n');
