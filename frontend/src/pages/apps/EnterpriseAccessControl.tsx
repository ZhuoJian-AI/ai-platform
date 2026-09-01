import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Badge, Button, Card, Checkbox, Drawer, Empty, Select, Space, Switch, Tag,
  Typography, message,
} from 'antd';
import {
  AppstoreOutlined, CheckCircleFilled, EyeOutlined, RobotOutlined, SafetyCertificateOutlined,
  TeamOutlined, UserOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  ApiError, enterpriseApplications, organizations, roles, users,
  type EnterpriseApplication,
  type EnterpriseApplicationManifestAccessRole,
  type EnterpriseApplicationManifestAction, type EnterpriseApplicationManifestModule,
  type EnterpriseApplicationModuleAccess, type EnterpriseApplicationPermission,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';
import './enterprise-access-control.css';

const OPERATION_PERMISSION: Record<string, EnterpriseApplicationPermission> = {
  query: 'ai_query', create: 'ai_create', update: 'ai_update', delete: 'ai_delete',
  approve: 'ai_approve', export: 'export',
};

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '角色模块权限保存失败';
}

function cloneAccess(value?: Record<string, EnterpriseApplicationModuleAccess>) {
  return structuredClone(value ?? {}) as Record<string, EnterpriseApplicationModuleAccess>;
}

function roleGrant(application: EnterpriseApplication | undefined, roleId: string | undefined) {
  return application?.grants.find(grant => grant.scope_type === 'role' && grant.scope_id === roleId);
}

function permissionsForActions(actions: EnterpriseApplicationManifestAction[], keys: string[]) {
  const selected = new Set(keys);
  return Array.from(new Set<EnterpriseApplicationPermission>([
    'view',
    ...actions
      .filter(action => selected.has(action.actionKey))
      .map(action => OPERATION_PERMISSION[action.operation])
      .filter(Boolean),
  ]));
}

function normalizeModuleAccess(
  module: EnterpriseApplicationManifestModule,
  current: EnterpriseApplicationModuleAccess | undefined,
  pageKey: string,
  enabled: boolean,
  actionKey?: string,
) {
  const next = structuredClone(current ?? {
    role: 'member', permissions: [], action_keys: [], page_access: {},
  }) as EnterpriseApplicationModuleAccess;
  const page = module.pages.find(item => item.pageKey === pageKey);
  if (!page) return next;
  if (!enabled && !actionKey) {
    delete next.page_access[pageKey];
  } else {
    const pageValue = next.page_access[pageKey] ?? { permissions: ['view'], action_keys: [] };
    if (actionKey) {
      pageValue.action_keys = enabled
        ? Array.from(new Set([...pageValue.action_keys, actionKey]))
        : pageValue.action_keys.filter(key => key !== actionKey);
    }
    const actions = module.actions.filter(action => pageValue.action_keys.includes(action.actionKey));
    pageValue.permissions = permissionsForActions(actions, pageValue.action_keys);
    next.page_access[pageKey] = pageValue;
  }
  next.action_keys = Array.from(new Set(Object.values(next.page_access).flatMap(item => item.action_keys)));
  next.permissions = Array.from(new Set(Object.values(next.page_access).flatMap(item => item.permissions)));
  return next;
}

function modulePermissionCount(access?: EnterpriseApplicationModuleAccess) {
  return access ? Object.keys(access.page_access ?? {}).length : 0;
}

export default function EnterpriseAccessControl() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const [selectedRoleId, setSelectedRoleId] = useState<string>();
  const [selectedAppId, setSelectedAppId] = useState<string>();
  const [selectedModuleKey, setSelectedModuleKey] = useState<string>();
  const [draft, setDraft] = useState<Record<string, EnterpriseApplicationModuleAccess>>({});
  const [legacyVisible, setLegacyVisible] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewUserId, setPreviewUserId] = useState<string>();
  const { nodeMap } = useOrgTree();

  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(item => item.is_default)?.id ?? orgs[0]?.id;
  const { data: roleList = [] } = useQuery({
    queryKey: ['roles', orgId], queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { data: appList = [], isLoading } = useQuery({
    queryKey: ['enterprise-applications', orgId],
    queryFn: () => orgId ? enterpriseApplications.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { data: userList = [] } = useQuery({
    queryKey: ['users', orgId], queryFn: () => orgId ? users.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const app = appList.find(item => item.id === selectedAppId) ?? appList[0];
  const role = roleList.find(item => item.id === selectedRoleId) ?? roleList.find(item => item.is_active);
  const { data: integration } = useQuery({
    queryKey: ['enterprise-application-integration', app?.id],
    queryFn: () => app ? enterpriseApplications.integration(app.id) : Promise.reject(),
    enabled: !!app, retry: false,
  });
  const modules = integration?.modules ?? [];
  const module = modules.find(item => item.moduleKey === selectedModuleKey) ?? modules[0];

  useEffect(() => {
    if (role && role.id !== selectedRoleId) setSelectedRoleId(role.id);
  }, [role, selectedRoleId]);
  useEffect(() => {
    if (app && app.id !== selectedAppId) setSelectedAppId(app.id);
  }, [app, selectedAppId]);
  useEffect(() => {
    if (module && module.moduleKey !== selectedModuleKey) setSelectedModuleKey(module.moduleKey);
  }, [module, selectedModuleKey]);
  useEffect(() => {
    const grant = roleGrant(app, role?.id);
    setDraft(cloneAccess(grant?.module_access));
    setLegacyVisible(Boolean(grant?.permissions.includes('view')));
  }, [app?.id, role?.id, app?.updated_at]);

  const selectedUser = userList.find(item => item.id === previewUserId) ?? userList[0];
  const previewRoleIds = new Set(selectedUser?.role_ids ?? []);
  const previewApps = useMemo(() => appList.map(application => {
    const grants = application.grants.filter(grant => grant.scope_type === 'role' && grant.scope_id && previewRoleIds.has(grant.scope_id));
    return {
      application,
      modules: Array.from(new Set(grants.flatMap(grant => Object.keys(grant.module_access ?? {})))),
      visible: grants.some(grant => grant.permissions.includes('view') || Object.keys(grant.module_access ?? {}).length),
    };
  }).filter(item => item.visible), [appList, selectedUser?.id]);

  useEffect(() => {
    const requestedUser = searchParams.get('user');
    if (requestedUser && userList.some(item => item.id === requestedUser)) {
      setPreviewUserId(requestedUser);
      setPreviewOpen(true);
    }
  }, [searchParams, userList]);

  const save = useMutation({
    mutationFn: async () => {
      if (!app || !role) throw new Error('请先选择企业模块和角色');
      const roleOnly = integration?.manifest?.contractRevision === '2.4';
      const other = app.grants
        .filter(grant => !(grant.scope_type === 'role' && grant.scope_id === role.id))
        .filter(grant => !roleOnly || grant.scope_type === 'role')
        .map(grant => ({
          scope_type: grant.scope_type, scope_id: grant.scope_id, permissions: grant.permissions,
          module_keys: grant.module_keys, module_access: grant.module_access,
        }));
      const moduleKeys = Object.keys(draft).filter(key => modulePermissionCount(draft[key]) > 0);
      const permissionSet = new Set<EnterpriseApplicationPermission>(
        moduleKeys.flatMap(key => draft[key].permissions),
      );
      if (moduleKeys.length || legacyVisible) permissionSet.add('view');
      if (permissionSet.size || moduleKeys.length) other.push({
        scope_type: 'role', scope_id: role.id,
        permissions: Array.from(permissionSet),
        module_keys: moduleKeys,
        module_access: Object.fromEntries(moduleKeys.map(key => [key, draft[key]])),
      });
      return enterpriseApplications.replaceGrants(app.id, other);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['enterprise-applications', orgId] });
      message.success(`已保存“${role?.name}”的模块权限`);
    },
    onError: error => message.error(errorText(error)),
  });

  const updatePage = (pageKey: string, enabled: boolean, actionKey?: string) => {
    if (!module) return;
    setDraft(current => {
      const next = cloneAccess(current);
      const access = normalizeModuleAccess(module, next[module.moduleKey], pageKey, enabled, actionKey);
      if (Object.keys(access.page_access).length) next[module.moduleKey] = access;
      else delete next[module.moduleKey];
      return next;
    });
  };

  const applySuggestion = (suggestion: EnterpriseApplicationManifestAccessRole) => {
    if (!module) return;
    const pageKeys = new Set(suggestion.pageKeys);
    const actionKeys = new Set(suggestion.actionKeys);
    const pageAccess = Object.fromEntries(module.pages
      .filter(page => pageKeys.has(page.pageKey))
      .map(page => {
        const keys = page.actionKeys.filter(key => actionKeys.has(key));
        return [page.pageKey, {
          permissions: permissionsForActions(module.actions, keys),
          action_keys: keys,
        }];
      }));
    setDraft(current => ({
      ...cloneAccess(current),
      [module.moduleKey]: {
        role: suggestion.roleKey,
        permissions: Array.from(new Set(Object.values(pageAccess).flatMap(item => item.permissions))),
        action_keys: Array.from(new Set(Object.values(pageAccess).flatMap(item => item.action_keys))),
        page_access: pageAccess,
      },
    }));
    message.success(`已将“${suggestion.name}”建议应用到当前平台角色，保存后才生效`);
  };

  const roleOptions = roleList.filter(item => item.is_active).map(item => ({ value: item.id, label: item.name }));
  const appOptions = appList.map(item => ({ value: item.id, label: item.name }));
  const currentAccess = module ? draft[module.moduleKey] : undefined;

  return <FinderShell background="#f6f7fb">
    <TitleBar
      icon={<SafetyCertificateOutlined />}
      title="角色与模块权限"
      titleExtra={<OrgSelect value={orgId} onChange={value => {
        setSelectedOrgId(value); setSelectedRoleId(undefined); setSelectedAppId(undefined);
      }} />}
      extra={<Space>
        <Button icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)}>模拟员工访问</Button>
        <Button type="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!app || !role}>
          保存权限
        </Button>
      </Space>}
    />
    <div className="access-summary">
      <div><span>授权主体</span><strong>角色</strong><small>员工可拥有多个角色，权限取并集</small></div>
      <div><span>身份归属</span><strong>唯一部门</strong><small>部门只决定组织身份与数据范围</small></div>
      <div><span>授权颗粒度</span><strong>大模块 → 子模块 → 页面 → 操作</strong><small>页面可见不等于 AI 可以执行</small></div>
    </div>
    <div className="access-workbench">
      <aside className="access-rail role-rail">
        <div className="rail-title"><TeamOutlined /> 选择角色</div>
        <Select
          showSearch optionFilterProp="label" value={role?.id} options={roleOptions}
          onChange={setSelectedRoleId} placeholder="选择岗位角色" style={{ width: '100%' }}
        />
        <div className="role-card">
          <Badge status={role?.is_active ? 'success' : 'default'} text={role?.is_active ? '角色已启用' : '未选择角色'} />
          <Typography.Title level={5}>{role?.name ?? '请选择角色'}</Typography.Title>
          <Typography.Paragraph type="secondary">{role?.description || '例如：销售业务员、质量审批员、成本会计。'}</Typography.Paragraph>
          {role && <Space wrap>
            <Tag color="geekblue">{role.data_scope === 'all' ? '全企业数据' : '受限数据范围'}</Tag>
            {role.is_builtin && <Tag>内置角色</Tag>}
          </Space>}
        </div>
        <div className="rail-help">
          <strong>开发负责人不等于有权限</strong>
          <span>Manifest 中的负责人只用于开发、验收和变更确认。员工能否进入系统，只看这里配置的角色。</span>
        </div>
      </aside>

      <aside className="access-rail module-rail">
        <div className="rail-title"><AppstoreOutlined /> 企业业务大模块</div>
        <Select value={app?.id} options={appOptions} onChange={value => {
          setSelectedAppId(value); setSelectedModuleKey(undefined);
        }} style={{ width: '100%' }} loading={isLoading} placeholder="选择业务大模块" />
        <div className="module-list">
          {modules.map(item => {
            const pageCount = modulePermissionCount(draft[item.moduleKey]);
            return <button
              key={item.moduleKey}
              className={item.moduleKey === module?.moduleKey ? 'module-item active' : 'module-item'}
              onClick={() => setSelectedModuleKey(item.moduleKey)}
            >
              <span className="module-symbol">{item.name.slice(0, 1)}</span>
              <span><strong>{item.name}</strong><small>{item.moduleKey}</small></span>
              {pageCount > 0 ? <Tag color="purple">{pageCount} 页</Tag> : <Tag>未授权</Tag>}
            </button>;
          })}
          {!modules.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现原生子模块" />}
        </div>
        {modules.length > 0 && <Alert
          type="success" showIcon
          message={`Manifest 已同步 · ${modules.length} 个子模块`}
          description="以后新增页面或 Action 默认无权，管理员确认后才开放。"
        />}
      </aside>

      <main className="permission-canvas">
        {module ? <>
          <div className="permission-heading">
            <div>
              <Typography.Text type="secondary">{app?.name} / {module.moduleKey}</Typography.Text>
              <Typography.Title level={4}>{module.name}</Typography.Title>
              <Typography.Text type="secondary">逐页决定能否看见，再决定页面内允许执行哪些操作。</Typography.Text>
            </div>
            <Tag color={currentAccess ? 'green' : 'default'} icon={currentAccess ? <CheckCircleFilled /> : undefined}>
              {currentAccess ? `已开放 ${modulePermissionCount(currentAccess)} 个页面` : '尚未授权'}
            </Tag>
          </div>
          {!!module.accessRoles?.length && <Alert
            type="info"
            showIcon
            className="role-suggestion"
            message="业务 AI 提供了角色建议，但不会自动授权"
            description={<Space wrap>
              {module.accessRoles.map(suggestion => <Button
                key={suggestion.roleKey}
                size="small"
                onClick={() => applySuggestion(suggestion)}
              >采用“{suggestion.name}”建议</Button>)}
            </Space>}
          />}
          <div className="page-grid">
            {module.pages.map(page => {
              const pageAccess = currentAccess?.page_access?.[page.pageKey];
              const enabled = Boolean(pageAccess);
              const pageActions = module.actions.filter(action => page.actionKeys.includes(action.actionKey));
              return <Card
                key={page.pageKey}
                className={enabled ? 'permission-card enabled' : 'permission-card'}
                title={<div className="page-title"><span><strong>{page.name}</strong><small>{page.pageKey}</small></span><Switch checked={enabled} onChange={value => updatePage(page.pageKey, value)} checkedChildren="可见" unCheckedChildren="隐藏" /></div>}
              >
                <div className="action-section-title"><span>页面与数据</span><Tag color={enabled ? 'blue' : undefined}>{enabled ? '允许进入' : '无权限'}</Tag></div>
                <div className="action-row disabled-fixed">
                  <Checkbox checked={enabled} disabled />查看页面与当前数据 <code>view</code>
                </div>
                <div className="action-section-title"><span><RobotOutlined /> 页面操作与 AI</span><small>页面按钮和 AI 共用同一 Action</small></div>
                {pageActions.length ? pageActions.map(action => {
                  const checked = Boolean(pageAccess?.action_keys?.includes(action.actionKey));
                  return <label key={action.actionKey} className={enabled ? 'action-row' : 'action-row muted'}>
                    <Checkbox
                      checked={checked}
                      disabled={!enabled}
                      onChange={event => updatePage(page.pageKey, event.target.checked, action.actionKey)}
                    />
                    <span className="action-name"><strong>{action.name}</strong><small>{action.actionKey}</small></span>
                    <Tag color={action.requiresConfirmation ? 'orange' : action.aiEnabled ? 'purple' : 'blue'}>
                      {action.requiresConfirmation ? '执行前确认' : action.aiEnabled ? 'AI 可调用' : '仅页面'}
                    </Tag>
                  </label>;
                }) : <Typography.Text type="secondary">此页面没有声明操作。</Typography.Text>}
              </Card>;
            })}
          </div>
        </> : <Card className="legacy-card">
          <Alert
            showIcon type="warning" message="旧系统兼容模式"
            description="这个应用没有原生 Manifest 页面目录，只能整站 iframe 授权，无法细分到页面和 AI Action。"
          />
          <div className="legacy-toggle"><span><strong>允许该角色进入整个旧系统</strong><small>旧系统仍可能要求用户再次登录</small></span><Switch checked={legacyVisible} onChange={setLegacyVisible} /></div>
        </Card>}
      </main>
    </div>

    <Drawer title="模拟员工访问" width={620} open={previewOpen} onClose={() => setPreviewOpen(false)}>
      <Alert type="info" showIcon message="这里展示员工登录后真正看到的结果" description="系统按该员工的多个角色取权限并集；部门本身不会直接增加模块权限。" style={{ marginBottom: 16 }} />
      <Select
        showSearch optionFilterProp="label" value={selectedUser?.id}
        options={userList.map(item => ({ value: item.id, label: item.display_name || item.username }))}
        onChange={setPreviewUserId} style={{ width: '100%', marginBottom: 16 }} placeholder="选择员工"
      />
      {selectedUser && <Card size="small" style={{ marginBottom: 16 }}>
        <Space direction="vertical">
          <Space><UserOutlined /><strong>{selectedUser.display_name || selectedUser.username}</strong><Tag>{nodeMap.get(`dept:${selectedUser.department_id}`)?.name ?? '未归属部门'}</Tag></Space>
          <Space wrap>{selectedUser.roles.map(item => <Tag color="purple" key={item.id}>{item.name}</Tag>)}</Space>
        </Space>
      </Card>}
      {previewApps.map(item => <Card key={item.application.id} title={item.application.name} size="small" style={{ marginBottom: 12 }}>
        <Space wrap>{item.modules.length ? item.modules.map(key => <Tag color="blue" key={key}>{key}</Tag>) : <Tag color="gold">旧系统整站</Tag>}</Space>
      </Card>)}
      {!previewApps.length && <Empty description="该员工当前没有企业模块权限" />}
    </Drawer>
  </FinderShell>;
}
