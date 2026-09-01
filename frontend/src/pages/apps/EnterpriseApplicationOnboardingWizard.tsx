import { useEffect, useMemo, useState } from 'react';
import {
  Alert, Button, Card, Descriptions, Form, Input, Modal, Result, Select, Space,
  Steps, Tag, Typography, message,
} from 'antd';
import {
  ApiOutlined, CheckCircleOutlined, CloudServerOutlined, LockOutlined,
  SafetyCertificateOutlined,
} from '@ant-design/icons';
import { useMutation, useQuery } from '@tanstack/react-query';
import {
  ApiError, enterpriseApplications, roles,
  type EnterpriseApplicationDiscovery,
  type EnterpriseApplicationManifestAccessRole,
  type EnterpriseApplicationModuleAccess,
  type EnterpriseApplicationOperation,
  type EnterpriseApplicationPermission,
  type EnterpriseApplicationScope,
} from '../../api/client';
import type { OrgNodeInfo } from '../../hooks/useOrgTree';
import './EnterpriseApplicationOnboardingWizard.css';

const OPERATION_PERMISSION: Record<EnterpriseApplicationOperation, EnterpriseApplicationPermission> = {
  query: 'ai_query', create: 'ai_create', update: 'ai_update', delete: 'ai_delete',
  approve: 'ai_approve', export: 'export',
};

function errorText(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback;
}

export default function EnterpriseApplicationOnboardingWizard({
  open, orgId, nodeMap, onClose, onComplete,
}: {
  open: boolean;
  orgId: string;
  nodeMap: Map<string, OrgNodeInfo>;
  onClose: () => void;
  onComplete: (applicationId: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [discovery, setDiscovery] = useState<EnterpriseApplicationDiscovery>();
  const [departmentMap, setDepartmentMap] = useState<Record<string, string>>({});
  const [roleMap, setRoleMap] = useState<Record<string, string>>({});
  const [connectionForm] = Form.useForm();
  const { data: roleList = [] } = useQuery({
    queryKey: ['roles', orgId],
    queryFn: () => roles.list(orgId),
    enabled: open && !!orgId,
  });

  useEffect(() => {
    if (!open) return;
    setStep(0); setDiscovery(undefined); setDepartmentMap({}); setRoleMap({}); connectionForm.resetFields();
  }, [connectionForm, open]);

  const discover = useMutation({
    mutationFn: (values: { base_url: string; auth_token: string }) =>
      enterpriseApplications.discover(orgId, values),
    onSuccess: (result) => {
      if (result.protocol_version !== 2) {
        message.error('该系统仍是 v1 协议，请先让开发 AI 使用最新版 Skill 升级');
        return;
      }
      const initial: Record<string, string> = {};
      result.modules.forEach((module) => module.departments.forEach((department) => {
        const key = `${module.moduleKey}:${department.key}`;
        if (department.platformDepartmentId) initial[key] = `dept:${department.platformDepartmentId}`;
      }));
      const initialRoles: Record<string, string> = {};
      result.modules.forEach((module) => (module.accessRoles ?? []).forEach((accessRole) => {
        const key = `${module.moduleKey}:${accessRole.roleKey}`;
        const match = roleList.find(role => role.code === accessRole.roleKey || role.name === accessRole.name);
        if (match) initialRoles[key] = match.id;
      }));
      setDepartmentMap(initial); setRoleMap(initialRoles); setDiscovery(result); setStep(1);
    },
    onError: (error) => message.error(errorText(error, '无法读取模块系统')),
  });

  const departmentRows = useMemo(() => (discovery?.modules ?? []).flatMap((module) => (
    module.departments.map((department) => ({
      key: `${module.moduleKey}:${department.key}`,
      moduleKey: module.moduleKey,
      moduleName: module.name,
      department,
    }))
  )), [discovery]);

  const accessRoleRows = useMemo(() => (discovery?.modules ?? []).flatMap((module) => (
    (module.accessRoles ?? []).map((accessRole) => ({
      key: `${module.moduleKey}:${accessRole.roleKey}`,
      moduleKey: module.moduleKey,
      moduleName: module.name,
      accessRole,
    }))
  )), [discovery]);
  const roleOnly = discovery?.manifest?.contractRevision === '2.4';
  const unresolvedDepartments = departmentRows.filter((row) => !departmentMap[row.key]);
  const unresolvedRoles = roleOnly ? accessRoleRows.filter((row) => !roleMap[row.key]) : [];

  const register = useMutation({
    mutationFn: async () => {
      if (!discovery) throw new Error('请先检查连接');
      const token = connectionForm.getFieldValue('auth_token') as string;
      let createdId: string | undefined;
      try {
        const created = await enterpriseApplications.create(orgId, {
          name: discovery.suggested_name,
          slug: discovery.suggested_slug,
          entry_url: discovery.entry_url,
          display_mode: 'embedded',
          sort_order: 0,
          is_active: true,
          assistant_enabled: true,
        });
        createdId = created.id;
        await enterpriseApplications.configureIntegration(created.id, {
          manifest_url: discovery.manifest_url,
          auth_token: token,
          sync_enabled: true,
        });
        const synced = await enterpriseApplications.syncIntegration(created.id);
        if (synced.status !== 'healthy') throw new Error(synced.detail || '首次同步失败');

        const grouped = new Map<string, {
          scope_type: EnterpriseApplicationScope;
          scope_id: string | null;
          permissions: Set<EnterpriseApplicationPermission>;
          module_keys: Set<string>;
          module_access: Record<string, EnterpriseApplicationModuleAccess>;
        }>();
        const addAccess = (
          scopeType: EnterpriseApplicationScope,
          scopeId: string | null,
          moduleKey: string,
          accessRole: EnterpriseApplicationManifestAccessRole,
        ) => {
          const groupKey = `${scopeType}:${scopeId ?? 'organization'}`;
          const group = grouped.get(groupKey) ?? {
            scope_type: scopeType,
            scope_id: scopeId,
            permissions: new Set<EnterpriseApplicationPermission>(['view']),
            module_keys: new Set<string>(),
            module_access: {},
          };
          const module = discovery.modules.find((item) => item.moduleKey === moduleKey)!;
          const enabledActionKeys = accessRole.actionKeys
            .filter((key) => module.actions.some((action) => action.aiEnabled && action.actionKey === key));
          const enabledPageKeys = new Set(accessRole.pageKeys);
          const permissions = new Set<EnterpriseApplicationPermission>(['view']);
          module.actions.filter((action) => enabledActionKeys.includes(action.actionKey)).forEach((action) => {
            permissions.add(OPERATION_PERMISSION[action.operation]);
          });
          permissions.forEach((permission) => group.permissions.add(permission));
          group.module_keys.add(moduleKey);
          const existing = group.module_access[moduleKey] ?? {
            role: accessRole.roleKey, permissions: [], action_keys: [], page_access: {},
          };
          (module.pages ?? []).filter((page) => enabledPageKeys.has(page.pageKey)).forEach((page) => {
              const pageActionKeys = page.actionKeys.filter((key) => enabledActionKeys.includes(key));
              const pagePermissions = new Set<EnterpriseApplicationPermission>(['view']);
              module.actions.filter((action) => pageActionKeys.includes(action.actionKey)).forEach((action) => {
                pagePermissions.add(OPERATION_PERMISSION[action.operation]);
              });
              const prior = existing.page_access[page.pageKey];
              existing.page_access[page.pageKey] = {
                permissions: Array.from(new Set([...(prior?.permissions ?? []), ...pagePermissions])),
                action_keys: Array.from(new Set([...(prior?.action_keys ?? []), ...pageActionKeys])),
              };
          });
          existing.permissions = Array.from(new Set([
            ...existing.permissions,
            ...Object.values(existing.page_access).flatMap(page => page.permissions),
          ]));
          existing.action_keys = Array.from(new Set([
            ...existing.action_keys,
            ...Object.values(existing.page_access).flatMap(page => page.action_keys),
          ]));
          group.module_access[moduleKey] = existing;
          grouped.set(groupKey, group);
        };
        if (roleOnly) {
          accessRoleRows.forEach((row) => {
            const selectedRole = roleList.find(role => role.id === roleMap[row.key]);
            if (!selectedRole) throw new Error(`“${row.accessRole.name}”尚未映射到平台角色`);
            addAccess('role', selectedRole.id, row.moduleKey, row.accessRole);
          });
        } else {
          departmentRows.forEach((row) => {
            const selected = departmentMap[row.key];
            const node = nodeMap.get(selected);
            if (!node) throw new Error(`“${row.department.name}”尚未映射到平台部门`);
            const module = discovery.modules.find(item => item.moduleKey === row.moduleKey)!;
            addAccess(node.type as EnterpriseApplicationScope, node.type === 'organization' ? null : node.id, row.moduleKey, {
              roleKey: row.department.role,
              name: row.department.name,
              pageKeys: row.department.pageKeys ?? module.pages.map(page => page.pageKey),
              actionKeys: row.department.actionKeys ?? module.actions.filter(action => action.aiEnabled).map(action => action.actionKey),
            });
          });
        }
        await enterpriseApplications.replaceGrants(created.id, Array.from(grouped.values()).map((grant) => ({
          scope_type: grant.scope_type,
          scope_id: grant.scope_id,
          permissions: Array.from(grant.permissions),
          module_keys: Array.from(grant.module_keys),
          module_access: grant.module_access,
        })));
        return created.id;
      } catch (error) {
        if (createdId) await enterpriseApplications.delete(createdId).catch(() => undefined);
        throw error;
      }
    },
    onSuccess: (id) => { setStep(3); onComplete(id); },
    onError: (error) => message.error(errorText(error, '模块系统登记失败')),
  });

  const footer = step === 0 ? [
    <Button key="cancel" onClick={onClose}>取消</Button>,
    <Button key="discover" type="primary" loading={discover.isPending} onClick={() => connectionForm.submit()}>
      检查并读取系统
    </Button>,
  ] : step === 1 ? [
    <Button key="back" onClick={() => setStep(0)}>上一步</Button>,
    <Button key="next" type="primary" disabled={unresolvedDepartments.length + unresolvedRoles.length > 0} onClick={() => setStep(2)}>核对接入</Button>,
  ] : step === 2 ? [
    <Button key="back" onClick={() => setStep(1)}>上一步</Button>,
    <Button key="register" type="primary" loading={register.isPending} onClick={() => register.mutate()}>
      确认登记并授权
    </Button>,
  ] : [<Button key="done" type="primary" onClick={onClose}>完成</Button>];

  return (
    <Modal
      title="接入模块系统"
      open={open}
      onCancel={register.isPending ? undefined : onClose}
      footer={footer}
      width={900}
      destroyOnClose
      className="subsystem-onboarding"
    >
      <Steps
        current={step}
        items={[
          { title: '连接系统' }, { title: '对齐组织与角色' }, { title: '核对接入' }, { title: '完成' },
        ]}
      />

      {step === 0 && <div className="subsystem-onboarding__stage">
        <div className="subsystem-onboarding__intro">
          <div className="subsystem-onboarding__mark"><CloudServerOutlined /></div>
          <div><Typography.Title level={4}>只需要系统域名和连接密钥</Typography.Title><Typography.Text type="secondary">平台会自动检查 HTTPS、健康状态、子模块、参与部门和 AI 操作，不读取业务数据库。</Typography.Text></div>
        </div>
        <Form form={connectionForm} layout="vertical" onFinish={(values) => discover.mutate(values)}>
          <Form.Item name="base_url" label="模块系统地址" rules={[{ required: true }, { type: 'url' }]} extra="例如：https://sample-review.aifabei.staging.zhuojianai.com">
            <Input size="large" prefix={<ApiOutlined />} placeholder="https://..." />
          </Form.Item>
          <Form.Item name="auth_token" label="连接密钥" rules={[{ required: true }, { min: 16 }]} extra="密钥只在保存时发送，并由平台加密保存，不会在页面回显。">
            <Input.Password size="large" prefix={<LockOutlined />} autoComplete="new-password" />
          </Form.Item>
          <Alert showIcon type="info" message="平台只接受公网 HTTPS 地址" description="内网地址、localhost、云元数据地址和跨域重定向会被拒绝。" />
        </Form>
      </div>}

      {step === 1 && discovery && <div className="subsystem-onboarding__stage">
        <Alert showIcon type="success" message={`${discovery.suggested_name}连接正常，发现 ${discovery.modules.length} 个子模块`} />
        <div className="subsystem-onboarding__module-grid">
          {discovery.modules.map((module) => <Card key={module.moduleKey} size="small" title={<Space><Tag color="blue">{module.moduleKey}</Tag>{module.name}</Space>}>
            <Typography.Text type="secondary">{module.actions.length} 个操作，其中 {module.actions.filter((action) => action.aiEnabled).length} 个允许 AI 调用</Typography.Text>
            <Typography.Title level={5}>开发与业务责任部门</Typography.Title>
            <div className="subsystem-onboarding__departments">
              {module.departments.map((department) => {
                const rowKey = `${module.moduleKey}:${department.key}`;
                return <div className="subsystem-onboarding__mapping" key={rowKey}>
                  <div><Typography.Text strong>{department.name}</Typography.Text><Tag color={department.role === 'owner' ? 'gold' : 'default'}>{department.role}</Tag><div><Typography.Text type="secondary">声明标识：{department.key} · 只用于开发、验收与数据责任</Typography.Text></div></div>
                  <Select
                    showSearch
                    optionFilterProp="label"
                    value={departmentMap[rowKey]}
                    placeholder="选择灼见中的对应部门"
                    style={{ width: 280 }}
                    options={Array.from(nodeMap.entries()).filter(([, node]) => node.orgId === orgId && node.type === 'department').map(([value, node]) => ({ value, label: node.name }))}
                    onChange={(value) => setDepartmentMap((current) => ({ ...current, [rowKey]: value }))}
                  />
                </div>;
              })}
            </div>
            {roleOnly && <>
              <Typography.Title level={5}>待管理员确认的平台角色</Typography.Title>
              <div className="subsystem-onboarding__departments">
                {(module.accessRoles ?? []).map((accessRole) => {
                  const rowKey = `${module.moduleKey}:${accessRole.roleKey}`;
                  return <div className="subsystem-onboarding__mapping" key={rowKey}>
                    <div><Typography.Text strong>{accessRole.name}</Typography.Text><Tag color="purple">{accessRole.roleKey}</Tag><div><Typography.Text type="secondary">建议开放 {accessRole.pageKeys.length} 个页面、{accessRole.actionKeys.length} 个 Action；此处映射后才会生成授权</Typography.Text></div></div>
                    <Select
                      showSearch
                      optionFilterProp="label"
                      value={roleMap[rowKey]}
                      placeholder="选择对应平台角色"
                      style={{ width: 280 }}
                      options={roleList.filter(role => role.is_active).map(role => ({ value: role.id, label: `${role.name} (${role.code})` }))}
                      onChange={(value) => setRoleMap(current => ({ ...current, [rowKey]: value }))}
                    />
                  </div>;
                })}
              </div>
            </>}
          </Card>)}
        </div>
        {unresolvedDepartments.length + unresolvedRoles.length > 0 && <Alert showIcon type="warning" message={`还有 ${unresolvedDepartments.length} 个责任部门、${unresolvedRoles.length} 个角色建议未匹配`} description="部门映射不授权；只有平台角色映射会生成页面和 Action 授权。" />}
      </div>}

      {step === 2 && discovery && <div className="subsystem-onboarding__stage">
        <Alert showIcon type="warning" message="部门只记录责任，员工访问只由角色决定" description="以后系统增加页面或操作可以自动同步，但新内容默认无权，需管理员再次确认。" />
        <Descriptions bordered column={2} size="small">
          <Descriptions.Item label="系统">{discovery.suggested_name}</Descriptions.Item>
          <Descriptions.Item label="协议"><Tag color="green">v{discovery.protocol_version}</Tag></Descriptions.Item>
          <Descriptions.Item label="入口" span={2}><Typography.Text copyable>{discovery.entry_url}</Typography.Text></Descriptions.Item>
          <Descriptions.Item label="子模块">{discovery.modules.length}</Descriptions.Item>
          <Descriptions.Item label="授权建议">{accessRoleRows.length} 个角色</Descriptions.Item>
        </Descriptions>
        {discovery.modules.map((module) => <Card key={module.moduleKey} size="small" title={module.name}>
          <Space wrap>
            {module.departments.map((department) => {
              const selected = nodeMap.get(departmentMap[`${module.moduleKey}:${department.key}`]);
              return <Tag key={department.key} icon={<SafetyCertificateOutlined />} color={department.role === 'owner' ? 'gold' : 'blue'}>{selected?.name} · {department.role}</Tag>;
            })}
          </Space>
          {roleOnly && <div className="subsystem-onboarding__actions">
            {(module.accessRoles ?? []).map(accessRole => {
              const selected = roleList.find(role => role.id === roleMap[`${module.moduleKey}:${accessRole.roleKey}`]);
              return <Tag key={accessRole.roleKey} color="purple">{accessRole.name} → {selected?.name}</Tag>;
            })}
          </div>}
          <div className="subsystem-onboarding__actions">
            {module.actions.map((action) => <Tag key={action.actionKey} color={action.requiresConfirmation ? 'red' : action.aiEnabled ? 'purple' : 'default'}>{action.name}{action.requiresConfirmation ? ' · 需确认' : action.aiEnabled ? ' · AI 可用' : ''}</Tag>)}
          </div>
        </Card>)}
      </div>}

      {step === 3 && <Result status="success" icon={<CheckCircleOutlined />} title="模块系统已接入" subTitle="子模块、页面、Action 与平台角色已建立关联。后续同步只更新目录，不会自动扩权。" />}
    </Modal>
  );
}
