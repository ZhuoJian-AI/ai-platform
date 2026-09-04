import { useEffect, useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Space, message } from 'antd';
import { ApartmentOutlined, SaveOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, organizations, type Organization } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';
import { useAuth } from '../../context/AuthContext';

type EnterpriseProfileValues = Pick<Organization, 'name' | 'description' | 'rate_limit_rpm' | 'rate_limit_tpm' | 'budget_cap_tokens' | 'budget_cap_credits'>;

export default function EnterpriseProfile() {
  const qc = useQueryClient();
  const { isOrgScoped } = useAuth();
  const enterpriseScoped = isOrgScoped();
  const [form] = Form.useForm<EnterpriseProfileValues>();
  const [selectedOrgId, setSelectedOrgId] = useState<string>();
  const { data: orgs = [] } = useQuery({ queryKey: ['orgs'], queryFn: organizations.list });
  const orgId = selectedOrgId ?? orgs.find(item => item.is_default)?.id ?? orgs[0]?.id;
  const organization = orgs.find(item => item.id === orgId);

  useEffect(() => {
    if (!organization) return;
    form.setFieldsValue({
      name: organization.name,
      description: organization.description,
      rate_limit_rpm: organization.rate_limit_rpm,
      rate_limit_tpm: organization.rate_limit_tpm,
      budget_cap_tokens: organization.budget_cap_tokens,
      budget_cap_credits: organization.budget_cap_credits,
    });
  }, [organization, form]);

  const save = useMutation({
    mutationFn: (values: EnterpriseProfileValues) => {
      if (!orgId) throw new Error('请先选择企业');
      // 企业管理员可以维护企业资料，但企业顶层额度只能由平台超级管理员调整。
      return organizations.update(orgId, enterpriseScoped ? {
        name: values.name,
        description: values.description,
      } : values);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['orgs'] });
      message.success('企业资料已保存');
    },
    onError: error => message.error(error instanceof ApiError ? error.message : '企业资料保存失败'),
  });

  return <FinderShell background="#f6f7fb">
    <TitleBar
      icon={<ApartmentOutlined />}
      title="企业资料"
      titleExtra={<OrgSelect value={orgId} onChange={setSelectedOrgId} />}
      extra={<Button type="primary" icon={<SaveOutlined />} onClick={() => form.submit()} loading={save.isPending} disabled={!organization}>保存</Button>}
    />
    <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
      <div style={{ maxWidth: 760, padding: 22, border: '1px solid #e5e7eb', borderRadius: 10, background: '#fff' }}>
        <Alert
          type="info"
          showIcon
          message={enterpriseScoped
            ? '企业顶层额度由平台超级管理员设置；你可以为部门、团队和 API Key 分配更严格的子额度。'
            : '这里维护企业资料与顶层额度；部门和团队请到“组织架构”管理。'}
          style={{ marginBottom: 20 }}
        />
        <Form form={form} layout="vertical" onFinish={values => save.mutate(values)}>
          <Form.Item label="企业标识"><Input value={organization?.slug} disabled /></Form.Item>
          <Form.Item name="name" label="企业名称" rules={[{ required: true, message: '请输入企业名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="企业说明"><Input.TextArea rows={4} /></Form.Item>
          <Space align="start" wrap size={16}>
            <Form.Item name="rate_limit_rpm" label="每分钟请求上限"><InputNumber min={1} placeholder="不限" disabled={enterpriseScoped} /></Form.Item>
            <Form.Item name="rate_limit_tpm" label="每分钟 Token 上限"><InputNumber min={1} placeholder="不限" disabled={enterpriseScoped} /></Form.Item>
            <Form.Item name="budget_cap_tokens" label="每月 Token 上限"><InputNumber min={0} placeholder="不限" disabled={enterpriseScoped} /></Form.Item>
            <Form.Item name="budget_cap_credits" label="每月调用额度" extra="一次平台 AI 操作准入扣 1；失败不退；供应商重试或故障转移不重复扣"><InputNumber min={0} precision={0} placeholder="不限" disabled={enterpriseScoped} /></Form.Item>
          </Space>
          {organization?.budget_cap_usd != null && (
            <Form.Item label="历史 USD 预算（只读，不再执行）">
              <Input value={`$${organization.budget_cap_usd}`} disabled />
            </Form.Item>
          )}
        </Form>
      </div>
    </div>
  </FinderShell>;
}
