import { useEffect, useState } from 'react';
import { Alert, Button, Form, Input, InputNumber, Space, message } from 'antd';
import { ApartmentOutlined, SaveOutlined } from '@ant-design/icons';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, organizations, type Organization } from '../../api/client';
import OrgSelect from '../../components/OrgSelect';
import { FinderShell, TitleBar } from '../../components/finder/primitives';

type EnterpriseProfileValues = Pick<Organization, 'name' | 'description' | 'rate_limit_rpm' | 'rate_limit_tpm' | 'budget_cap_tokens'>;

export default function EnterpriseProfile() {
  const qc = useQueryClient();
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
    });
  }, [organization, form]);

  const save = useMutation({
    mutationFn: (values: EnterpriseProfileValues) => {
      if (!orgId) throw new Error('请先选择企业');
      return organizations.update(orgId, values);
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
          message="这里维护企业本身的资料；部门和团队请到“组织架构”管理。"
          style={{ marginBottom: 20 }}
        />
        <Form form={form} layout="vertical" onFinish={values => save.mutate(values)}>
          <Form.Item label="企业标识"><Input value={organization?.slug} disabled /></Form.Item>
          <Form.Item name="name" label="企业名称" rules={[{ required: true, message: '请输入企业名称' }]}>
            <Input />
          </Form.Item>
          <Form.Item name="description" label="企业说明"><Input.TextArea rows={4} /></Form.Item>
          <Space align="start" wrap size={16}>
            <Form.Item name="rate_limit_rpm" label="每分钟请求上限"><InputNumber min={1} placeholder="不限" /></Form.Item>
            <Form.Item name="rate_limit_tpm" label="每分钟 Token 上限"><InputNumber min={1} placeholder="不限" /></Form.Item>
            <Form.Item name="budget_cap_tokens" label="Token 预算上限"><InputNumber min={0} placeholder="不限" /></Form.Item>
          </Space>
        </Form>
      </div>
    </div>
  </FinderShell>;
}
