import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Checkbox, Drawer, Empty, Form, Input, Modal, Select, Space,
  Switch, Tag, message,
} from 'antd';
import {
  EyeOutlined, PlusOutlined, SafetyCertificateOutlined, UserOutlined,
} from '@ant-design/icons';
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import {
  ApiError, enterpriseApplications, organizations, roles, users,
  type EnterpriseApplication,
  type EnterpriseApplicationIntegration,
  type EnterpriseApplicationManifestAction,
  type EnterpriseApplicationManifestModule,
  type EnterpriseApplicationModuleAccess,
  type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission,
} from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useOrgTree } from '../../hooks/useOrgTree';
import './enterprise-access-control.css';

type PageAccess = EnterpriseApplicationModuleAccess['page_access'][string];
type AppDraft = Record<string, EnterpriseApplicationModuleAccess>;
type DraftByApplication = Record<string, AppDraft>;

const OPERATION_COLUMNS: Array<{ key: EnterpriseApplicationOperation; label: string }> = [
  { key: 'query', label: '查询' },
  { key: 'create', label: '新增' },
  { key: 'update', label: '修改' },
  { key: 'approve', label: '审批' },
  { key: 'delete', label: '删除' },
];

const OPERATION_PERMISSION: Record<EnterpriseApplicationOperation, EnterpriseApplicationPermission> = {
  query: 'ai_query', create: 'ai_create', update: 'ai_update', delete: 'ai_delete',
  approve: 'ai_approve', export: 'export',
};

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : '角色权限保存失败';
}

function cloneDraft(value?: AppDraft) {
  return structuredClone(value ?? {}) as AppDraft;
}

function roleGrant(application: EnterpriseApplication, roleId?: string) {
  return application.grants.find(grant => grant.scope_type === 'role' && grant.scope_id === roleId);
}

function selectedActions(module: EnterpriseApplicationManifestModule, keys: string[]) {
  const selected = new Set(keys);
  return module.actions.filter(action => selected.has(action.actionKey));
}

function permissionsForActions(actions: EnterpriseApplicationManifestAction[]) {
  return Array.from(new Set<EnterpriseApplicationPermission>([
    'view', ...actions.map(action => OPERATION_PERMISSION[action.operation]),
  ]));
}

function rebuildModuleAccess(
  module: EnterpriseApplicationManifestModule,
  current: EnterpriseApplicationModuleAccess,
) {
  const pageAccess = Object.fromEntries(Object.entries(current.page_access ?? {})
    .filter(([pageKey]) => module.pages.some(page => page.pageKey === pageKey))
    .map(([pageKey, page]) => {
      const manifestPage = module.pages.find(item => item.pageKey === pageKey)!;
      const allowedKeys = page.action_keys.filter(key => manifestPage.actionKeys.includes(key));
      return [pageKey, {
        permissions: permissionsForActions(selectedActions(module, allowedKeys)),
        action_keys: allowedKeys,
        ai_enabled: page.ai_enabled ?? true,
      } satisfies PageAccess];
    }));
  return {
    role: current.role || 'member',
    permissions: Array.from(new Set(Object.values(pageAccess).flatMap(page => page.permissions))),
    action_keys: Array.from(new Set(Object.values(pageAccess).flatMap(page => page.action_keys))),
    page_access: pageAccess,
  } satisfies EnterpriseApplicationModuleAccess;
}

function pageCount(access?: EnterpriseApplicationModuleAccess) {
  return Object.keys(access?.page_access ?? {}).length;
}

function pageActionsForOperation(
  module: EnterpriseApplicationManifestModule,
  pageKey: string,
  operation: EnterpriseApplicationOperation,
) {
  const page = module.pages.find(item => item.pageKey === pageKey);
  if (!page) return [];
  return module.actions.filter(action => (
    action.operation === operation && page.actionKeys.includes(action.actionKey)
  ));
}

function roleCode(value: string) {
  return value.toLowerCase().trim().replace(/[^a-z0-9_.:-]+/g, '_').replace(/^_+|_+$/g, '');
}

export default function EnterpriseAccessControl() {
  const qc = useQueryClient();
  const [searchParams] = useSearchParams();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const [selectedRoleId, setSelectedRoleId] = useState<string>();
  const [systemFilter, setSystemFilter] = useState<string>('all');
  const [onlyGranted, setOnlyGranted] = useState(false);
  const [drafts, setDrafts] = useState<DraftByApplication>({});
  const [legacyVisible, setLegacyVisible] = useState<Record<string, boolean>>({});
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewUserId, setPreviewUserId] = useState<string>();
  const [roleModalOpen, setRoleModalOpen] = useState(false);
  const [roleForm] = Form.useForm<{ name: string; code: string; description?: string }>();
  const { nodeMap } = useOrgTree();

  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(item => item.is_default)?.id ?? orgs[0]?.id;
  const { data: roleList = [] } = useQuery({
    queryKey: ['roles', orgId],
    queryFn: () => orgId ? roles.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { data: appList = [], isLoading: appsLoading } = useQuery({
    queryKey: ['enterprise-applications', orgId],
    queryFn: () => orgId ? enterpriseApplications.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const { data: userList = [] } = useQuery({
    queryKey: ['users', orgId],
    queryFn: () => orgId ? users.list(orgId) : Promise.resolve([]), enabled: !!orgId,
  });
  const integrationQueries = useQueries({
    queries: appList.map(application => ({
      queryKey: ['enterprise-application-integration', application.id],
      queryFn: () => enterpriseApplications.integration(application.id), retry: false,
    })),
  });
  const integrationVersion = integrationQueries.map(query => query.dataUpdatedAt).join(':');
  const integrationsLoading = integrationQueries.some(query => query.isLoading);
  const integrationByAppId = useMemo(() => Object.fromEntries(appList.map((application, index) => (
    [application.id, integrationQueries[index]?.data as EnterpriseApplicationIntegration | undefined]
  ))), [appList, integrationVersion]);
  const role = roleList.find(item => item.id === selectedRoleId) ?? roleList.find(item => item.is_active);

  useEffect(() => {
    if (role && role.id !== selectedRoleId) setSelectedRoleId(role.id);
  }, [role, selectedRoleId]);

  useEffect(() => {
    if (!role) {
      setDrafts({});
      setLegacyVisible({});
      return;
    }
    const nextDrafts: DraftByApplication = {};
    const nextLegacy: Record<string, boolean> = {};
    appList.forEach(application => {
      const grant = roleGrant(application, role.id);
      nextDrafts[application.id] = cloneDraft(grant?.module_access);
      nextLegacy[application.id] = Boolean(
        grant?.permissions.includes('view') && !Object.keys(grant.module_access ?? {}).length,
      );
    });
    setDrafts(nextDrafts);
    setLegacyVisible(nextLegacy);
  }, [role?.id, appList, integrationVersion]);

  useEffect(() => {
    const requestedUser = searchParams.get('user');
    if (requestedUser && userList.some(item => item.id === requestedUser)) {
      setPreviewUserId(requestedUser);
      setPreviewOpen(true);
    }
  }, [searchParams, userList]);

  const createRole = useMutation({
    mutationFn: async (values: { name: string; code: string; description?: string }) => {
      if (!orgId) throw new Error('请先选择企业');
      return roles.create(orgId, { ...values, is_active: true });
    },
    onSuccess: created => {
      // 先把新角色写入缓存再选中，避免查询刷新完成前 fallback effect
      // 把选择悄悄切回列表里的第一个角色。
      qc.setQueryData(['roles', orgId], (current: typeof roleList | undefined) => [
        ...(current ?? []).filter(item => item.id !== created.id), created,
      ]);
      setSelectedRoleId(created.id);
      qc.invalidateQueries({ queryKey: ['roles', orgId] });
      setRoleModalOpen(false);
      roleForm.resetFields();
      message.success('角色已创建，现在可以直接配置页面权限');
    },
    onError: error => message.error(errorText(error)),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!role) throw new Error('请先选择角色');
      await Promise.all(appList.map(application => {
        const activeRoleIds = new Set(roleList.filter(item => item.is_active).map(item => item.id));
        // 本页是唯一的企业模块授权入口：无论子系统仍报告 2.3 还是已经升级
        // 到 2.4，都只提交角色授权。历史部门/团队/用户授权会在管理员保存时
        // 被收敛掉，部门不再暗中扩大页面权限。
        const retained = application.grants
          .filter(grant => !(grant.scope_type === 'role' && grant.scope_id === role.id))
          .filter(grant => grant.scope_type === 'role' && grant.scope_id && activeRoleIds.has(grant.scope_id))
          .map(grant => ({
            scope_type: grant.scope_type, scope_id: grant.scope_id,
            permissions: grant.permissions, module_keys: grant.module_keys,
            module_access: grant.module_access,
          }));
        const applicationDraft = drafts[application.id] ?? {};
        const moduleKeys = Object.keys(applicationDraft).filter(key => pageCount(applicationDraft[key]) > 0);
        const permissions = Array.from(new Set<EnterpriseApplicationPermission>(
          moduleKeys.flatMap(key => applicationDraft[key].permissions),
        ));
        if (moduleKeys.length || legacyVisible[application.id]) permissions.push('view');
        if (permissions.length || moduleKeys.length) retained.push({
          scope_type: 'role', scope_id: role.id,
          permissions: Array.from(new Set(permissions)), module_keys: moduleKeys,
          module_access: Object.fromEntries(moduleKeys.map(key => [key, applicationDraft[key]])),
        });
        return enterpriseApplications.replaceGrants(application.id, retained);
      }));
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['enterprise-applications', orgId] });
      message.success(`已保存“${role?.name}”在全部企业模块中的权限`);
    },
    onError: error => message.error(errorText(error)),
  });

  const updatePage = (
    applicationId: string,
    module: EnterpriseApplicationManifestModule,
    pageKey: string,
    updater: (current: PageAccess | undefined) => PageAccess | undefined,
  ) => {
    setDrafts(current => {
      const next = structuredClone(current) as DraftByApplication;
      const appDraft = next[applicationId] ?? {};
      const moduleAccess = structuredClone(appDraft[module.moduleKey] ?? {
        role: 'member', permissions: [], action_keys: [], page_access: {},
      }) as EnterpriseApplicationModuleAccess;
      const pageAccess = updater(moduleAccess.page_access[pageKey]);
      if (pageAccess) moduleAccess.page_access[pageKey] = pageAccess;
      else delete moduleAccess.page_access[pageKey];
      const rebuilt = rebuildModuleAccess(module, moduleAccess);
      if (pageCount(rebuilt)) appDraft[module.moduleKey] = rebuilt;
      else delete appDraft[module.moduleKey];
      next[applicationId] = appDraft;
      return next;
    });
  };

  const togglePage = (
    applicationId: string, module: EnterpriseApplicationManifestModule, pageKey: string, enabled: boolean,
  ) => updatePage(applicationId, module, pageKey, current => enabled ? (current ?? {
    permissions: ['view'], action_keys: [], ai_enabled: false,
  }) : undefined);

  const toggleOperation = (
    applicationId: string, module: EnterpriseApplicationManifestModule, pageKey: string,
    operation: EnterpriseApplicationOperation, enabled: boolean,
  ) => {
    const operationKeys = new Set(pageActionsForOperation(module, pageKey, operation).map(action => action.actionKey));
    updatePage(applicationId, module, pageKey, current => {
      const next = structuredClone(current ?? {
        permissions: ['view'], action_keys: [], ai_enabled: false,
      }) as PageAccess;
      next.action_keys = enabled
        ? Array.from(new Set([...next.action_keys, ...operationKeys]))
        : next.action_keys.filter(key => !operationKeys.has(key));
      return next;
    });
  };

  const toggleAi = (
    applicationId: string, module: EnterpriseApplicationManifestModule, pageKey: string, enabled: boolean,
  ) => updatePage(applicationId, module, pageKey, current => current ? { ...current, ai_enabled: enabled } : current);

  const toggleModule = (
    applicationId: string, module: EnterpriseApplicationManifestModule, enabled: boolean,
  ) => {
    setDrafts(current => {
      const next = structuredClone(current) as DraftByApplication;
      const appDraft = next[applicationId] ?? {};
      if (!enabled) {
        delete appDraft[module.moduleKey];
      } else {
        const pageAccess = Object.fromEntries(module.pages.map(page => {
          const queryKeys = page.queryActionKey && page.actionKeys.includes(page.queryActionKey)
            ? [page.queryActionKey] : [];
          return [page.pageKey, {
            permissions: permissionsForActions(selectedActions(module, queryKeys)),
            action_keys: queryKeys, ai_enabled: false,
          } satisfies PageAccess];
        }));
        appDraft[module.moduleKey] = rebuildModuleAccess(module, {
          role: 'member', permissions: [], action_keys: [], page_access: pageAccess,
        });
      }
      next[applicationId] = appDraft;
      return next;
    });
  };

  const selectedUser = userList.find(item => item.id === previewUserId) ?? userList[0];
  const previewRoleIds = new Set(selectedUser?.role_ids ?? []);
  const previewApps = useMemo(() => appList.map(application => {
    const integration = integrationByAppId[application.id];
    const grants = application.grants.filter(grant => (
      grant.scope_type === 'role' && grant.scope_id && previewRoleIds.has(grant.scope_id)
    ));
    const modules = (integration?.modules ?? []).map(module => {
      const pageKeys = Array.from(new Set(grants.flatMap(grant => (
        Object.keys(grant.module_access?.[module.moduleKey]?.page_access ?? {})
      ))));
      return {
        name: module.name,
        pages: pageKeys.map(pageKey => module.pages.find(page => page.pageKey === pageKey)?.name ?? pageKey),
      };
    }).filter(module => module.pages.length);
    const legacy = !integration?.modules?.length && grants.some(grant => grant.permissions.includes('view'));
    return { application, modules, legacy, visible: legacy || modules.length > 0 };
  }).filter(item => item.visible), [appList, integrationByAppId, selectedUser?.id]);

  const visibleApplications = appList.filter(application => systemFilter === 'all' || application.id === systemFilter);
  const grantedPageTotal = Object.values(drafts).reduce((total, appDraft) => (
    total + Object.values(appDraft).reduce((sum, access) => sum + pageCount(access), 0)
  ), 0);

  const renderNativeApplication = (application: EnterpriseApplication, integration: EnterpriseApplicationIntegration) => {
    const applicationDraft = drafts[application.id] ?? {};
    const modules = integration.modules.map(module => ({
      module,
      pages: onlyGranted
        ? module.pages.filter(page => Boolean(applicationDraft[module.moduleKey]?.page_access?.[page.pageKey]))
        : module.pages,
    })).filter(item => item.pages.length);
    if (!modules.length) return [];
    const applicationRowCount = modules.reduce((sum, item) => sum + item.pages.length, 0);
    let applicationCellRendered = false;
    return modules.flatMap(({ module, pages }) => pages.map((page, pageIndex) => {
      const access = applicationDraft[module.moduleKey]?.page_access?.[page.pageKey];
      const row = <tr key={`${application.id}:${module.moduleKey}:${page.pageKey}`}>
        {!applicationCellRendered && <td rowSpan={applicationRowCount} className="system-cell">
          <strong>{application.name}</strong><small>{application.slug}</small><Tag color="blue">原生接入</Tag>
        </td>}
        {pageIndex === 0 && <td rowSpan={pages.length} className="module-cell">
          <label>
            <Checkbox
              checked={pageCount(applicationDraft[module.moduleKey]) === module.pages.length && module.pages.length > 0}
              indeterminate={pageCount(applicationDraft[module.moduleKey]) > 0 && pageCount(applicationDraft[module.moduleKey]) < module.pages.length}
              onChange={event => toggleModule(application.id, module, event.target.checked)}
            />
            <span><strong>{module.name}</strong><small>{module.moduleKey}</small></span>
          </label>
        </td>}
        <td className="page-cell"><strong>{page.name}</strong><small>{page.pageKey}</small></td>
        <td><Checkbox checked={Boolean(access)} onChange={event => togglePage(application.id, module, page.pageKey, event.target.checked)} /></td>
        {OPERATION_COLUMNS.map(operation => {
          const actions = pageActionsForOperation(module, page.pageKey, operation.key);
          const granted = actions.length > 0 && actions.every(action => access?.action_keys.includes(action.actionKey));
          return <td key={operation.key}><Checkbox
            disabled={!access || actions.length === 0} checked={granted}
            onChange={event => toggleOperation(application.id, module, page.pageKey, operation.key, event.target.checked)}
          /></td>;
        })}
        <td><Checkbox
          disabled={!access || !module.actions.some(action => action.aiEnabled && page.actionKeys.includes(action.actionKey))}
          checked={Boolean(access?.ai_enabled)}
          onChange={event => toggleAi(application.id, module, page.pageKey, event.target.checked)}
        /></td>
      </tr>;
      applicationCellRendered = true;
      return row;
    }));
  };

  const renderLegacyApplication = (application: EnterpriseApplication) => {
    if (onlyGranted && !legacyVisible[application.id]) return [];
    return [<tr key={`${application.id}:legacy`}>
      <td className="system-cell"><strong>{application.name}</strong><small>{application.slug}</small><Tag color="gold">旧系统</Tag></td>
      <td className="module-cell"><strong>整站兼容</strong><small>无 Manifest</small></td>
      <td className="page-cell"><strong>整个应用</strong><small>iframe 整站授权</small></td>
      <td><Checkbox checked={Boolean(legacyVisible[application.id])} onChange={event => setLegacyVisible(current => ({
        ...current, [application.id]: event.target.checked,
      }))} /></td>
      {OPERATION_COLUMNS.map(operation => <td key={operation.key}><Checkbox disabled /></td>)}
      <td><Checkbox disabled /></td>
    </tr>];
  };

  return <FinderShell background="#f6f7fb">
    <TitleBar
      icon={<SafetyCertificateOutlined />}
      title="角色权限"
      titleExtra={<OrgSelect value={orgId} onChange={value => {
        setSelectedOrgId(value); setSelectedRoleId(undefined); setSystemFilter('all');
      }} />}
      extra={<Space>
        <Button icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)}>模拟员工查看</Button>
        <Button type="primary" onClick={() => save.mutate()} loading={save.isPending} disabled={!role || integrationsLoading}>保存权限</Button>
      </Space>}
    />

    <div className="permission-page">
      <Alert
        type="info" showIcon
        message="鉴权后聚合：员工只会看到其角色已获授权的系统、业务子模块和页面"
        description="部门只记录员工属于哪里；一个员工可拥有多个角色，最终权限取角色并集。新接入的页面和 Action 默认无权。"
      />

      <section className="permission-toolbar">
        <div className="toolbar-field">
          <span>配置角色</span>
          <Select
            showSearch optionFilterProp="label" value={role?.id}
            getPopupContainer={trigger => trigger.parentElement ?? document.body}
            options={roleList.filter(item => item.is_active).map(item => ({ value: item.id, label: item.name }))}
            onChange={setSelectedRoleId} placeholder="选择角色"
          />
        </div>
        <Button icon={<PlusOutlined />} onClick={() => { roleForm.resetFields(); setRoleModalOpen(true); }}>新建角色</Button>
        <div className="toolbar-field system-filter">
          <span>查看系统</span>
          <Select
            value={systemFilter}
            options={[{ value: 'all', label: '全部企业模块' }, ...appList.map(application => ({
              value: application.id, label: application.name,
            }))]}
            onChange={setSystemFilter}
          />
        </div>
        <label className="granted-filter"><Switch checked={onlyGranted} onChange={setOnlyGranted} size="small" />只看已授权</label>
        <div className="permission-count"><strong>{grantedPageTotal}</strong><span>个页面已授权</span></div>
      </section>

      <section className="permission-table-card">
        <div className="permission-table-scroll">
          <table className="permission-matrix">
            <thead><tr>
              <th>企业模块</th><th>业务子模块</th><th>最小模块页面</th><th>显示</th>
              {OPERATION_COLUMNS.map(operation => <th key={operation.key}>{operation.label}</th>)}
              <th>AI 可用</th>
            </tr></thead>
            <tbody>{visibleApplications.flatMap(application => {
              const queryIndex = appList.findIndex(item => item.id === application.id);
              if (integrationQueries[queryIndex]?.isLoading) return [];
              const integration = integrationByAppId[application.id];
              return integration?.modules?.length
                ? renderNativeApplication(application, integration)
                : renderLegacyApplication(application);
            })}</tbody>
          </table>
          {!appsLoading && !visibleApplications.length && <Empty description="暂无企业模块" />}
          {(appsLoading || integrationsLoading) && <div className="matrix-loading">正在读取企业模块目录…</div>}
        </div>
        <footer className="permission-footer">
          <span>“显示”决定能否进入页面；操作列决定页面按钮；“AI 可用”是额外总开关。</span>
          <strong>当前角色：{role?.name ?? '未选择'}</strong>
        </footer>
      </section>
    </div>

    <Modal
      open={roleModalOpen} title="新建角色" onCancel={() => setRoleModalOpen(false)}
      onOk={() => roleForm.submit()} confirmLoading={createRole.isPending} destroyOnClose
    >
      <Form form={roleForm} layout="vertical" onFinish={values => createRole.mutate(values)}>
        <Form.Item name="name" label="角色名称" rules={[{ required: true, message: '请输入角色名称' }]}>
          <Input placeholder="例如：质量审批员" onChange={event => {
            if (!roleForm.isFieldTouched('code')) roleForm.setFieldValue('code', roleCode(event.target.value));
          }} />
        </Form.Item>
        <Form.Item name="code" label="角色标识" rules={[
          { required: true, message: '请输入角色标识' },
          { pattern: /^[a-z0-9_.:-]+$/, message: '仅支持小写字母、数字和 _ . : -' },
        ]}><Input placeholder="quality_approver" /></Form.Item>
        <Form.Item name="description" label="说明"><Input.TextArea rows={3} /></Form.Item>
        <Alert type="info" showIcon message="角色创建后不会自动获得任何企业模块权限" />
      </Form>
    </Modal>

    <Drawer title="模拟员工查看" width={640} open={previewOpen} onClose={() => setPreviewOpen(false)}>
      <Alert
        type="info" showIcon message="这是鉴权后聚合结果"
        description="系统按员工拥有的全部角色取并集；部门本身不会增加任何系统或页面权限。"
        style={{ marginBottom: 16 }}
      />
      <Select
        showSearch optionFilterProp="label" value={selectedUser?.id}
        options={userList.map(item => ({ value: item.id, label: item.display_name || item.username }))}
        onChange={setPreviewUserId} style={{ width: '100%', marginBottom: 16 }} placeholder="选择员工"
      />
      {selectedUser && <div className="preview-identity">
        <UserOutlined />
        <div><strong>{selectedUser.display_name || selectedUser.username}</strong><span>{nodeMap.get(`dept:${selectedUser.department_id}`)?.name ?? '未归属部门'}</span></div>
        <Space wrap>{selectedUser.roles.map(item => <Tag color="purple" key={item.id}>{item.name}</Tag>)}</Space>
      </div>}
      <div className="preview-app-list">
        {previewApps.map(item => <section key={item.application.id}>
          <h4>{item.application.name}</h4>
          {item.legacy ? <Tag color="gold">旧系统整站</Tag> : item.modules.map(module => <div key={module.name}>
            <strong>{module.name}</strong>
            <Space wrap>{module.pages.map(page => <Tag color="blue" key={page}>{page}</Tag>)}</Space>
          </div>)}
        </section>)}
        {!previewApps.length && <Empty description="该员工当前没有企业模块权限" />}
      </div>
    </Drawer>
  </FinderShell>;
}
