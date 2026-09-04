import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  Modal,
  QRCode,
  Space,
  Spin,
  Typography,
  message,
} from 'antd';
import { CopyOutlined, SafetyCertificateOutlined } from '@ant-design/icons';
import { adminFetch, setAdminCsrfToken } from '../auth/adminSession';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

interface MfaSetup {
  secret: string;
  provisioningUri: string;
}

export interface MfaEnrollmentCompletion {
  admin: unknown;
  csrfToken: string | null;
}

interface ConfirmResponse {
  recovery_codes?: unknown;
  csrf_token?: unknown;
  admin?: unknown;
}

function errorDetail(body: unknown, fallback: string): string {
  if (body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string') {
    return (body as { detail: string }).detail;
  }
  return fallback;
}

async function copyText(value: string) {
  try {
    await navigator.clipboard.writeText(value);
    message.success('已复制');
  } catch {
    message.warning('复制失败，请手动保存');
  }
}

/**
 * Mandatory administrator MFA enrollment gate. It deliberately has no close
 * path: until confirmation succeeds, the backend denies every business API.
 */
export default function AdminMfaEnrollment({
  open,
  onConfirmed,
}: {
  open: boolean;
  onConfirmed: (completion: MfaEnrollmentCompletion) => void;
}) {
  const [setup, setSetup] = useState<MfaSetup | null>(null);
  const [setupLoading, setSetupLoading] = useState(false);
  const [confirmLoading, setConfirmLoading] = useState(false);
  const [error, setError] = useState('');
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [completion, setCompletion] = useState<MfaEnrollmentCompletion | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [form] = Form.useForm<{ code: string }>();
  const setupStarted = useRef(false);

  const loadSetup = useCallback(async () => {
    setupStarted.current = true;
    setSetupLoading(true);
    setError('');
    try {
      const response = await adminFetch(`${BASE_URL}/api/v1/auth/mfa/setup`, {
        method: 'POST',
      }, { organizationScoped: false });
      const body = await response.json().catch(() => ({})) as Record<string, unknown>;
      if (!response.ok) throw new Error(errorDetail(body, '无法开始绑定身份验证器'));
      if (typeof body.secret !== 'string' || typeof body.provisioning_uri !== 'string') {
        throw new Error('服务器返回的 MFA 配置不完整');
      }
      setSetup({ secret: body.secret, provisioningUri: body.provisioning_uri });
    } catch (reason) {
      setupStarted.current = false;
      setError(reason instanceof Error ? reason.message : '无法开始绑定身份验证器');
    } finally {
      setSetupLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      setupStarted.current = false;
      setSetup(null);
      setRecoveryCodes(null);
      setCompletion(null);
      setAcknowledged(false);
      setError('');
      form.resetFields();
      return;
    }
    // The ref prevents React StrictMode's development effect replay from
    // rotating the server-side seed twice and invalidating the first QR code.
    if (!setupStarted.current) void loadSetup();
  }, [form, loadSetup, open]);

  const confirm = async ({ code }: { code: string }) => {
    setConfirmLoading(true);
    setError('');
    try {
      const response = await adminFetch(`${BASE_URL}/api/v1/auth/mfa/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: code.trim() }),
      }, { organizationScoped: false });
      const body = await response.json().catch(() => ({})) as ConfirmResponse;
      if (!response.ok) throw new Error(errorDetail(body, '验证码校验失败'));
      const codes = Array.isArray(body.recovery_codes)
        ? body.recovery_codes.filter((value): value is string => typeof value === 'string' && value.length > 0)
        : [];
      if (!body.admin || codes.length === 0) throw new Error('服务器未返回完整的 MFA 确认结果');
      const csrfToken = typeof body.csrf_token === 'string' ? body.csrf_token : null;
      setAdminCsrfToken(csrfToken);
      setCompletion({ admin: body.admin, csrfToken });
      setRecoveryCodes(codes);
      setSetup(null);
      form.resetFields();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '验证码校验失败');
    } finally {
      setConfirmLoading(false);
    }
  };

  const finish = () => {
    if (!completion || !acknowledged) return;
    try {
      onConfirmed(completion);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '无法完成 MFA 绑定');
    }
  };

  return (
    <Modal
      title={<Space><SafetyCertificateOutlined />绑定管理员双重验证</Space>}
      open={open}
      closable={false}
      maskClosable={false}
      keyboard={false}
      footer={recoveryCodes ? (
        <Button type="primary" disabled={!acknowledged || !completion} onClick={finish}>
          我已保存，进入管理后台
        </Button>
      ) : null}
      width={520}
      destroyOnClose
    >
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 16 }} />}

      {setupLoading && !setup ? (
        <div style={{ minHeight: 220, display: 'grid', placeItems: 'center' }}><Spin /></div>
      ) : recoveryCodes ? (
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Alert
            type="success"
            showIcon
            message="双重验证已启用"
            description="下面的恢复码每个只能使用一次，而且离开本页后不会再次显示。"
          />
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
            gap: 8,
            padding: 14,
            borderRadius: 8,
            background: '#f5f5f5',
            fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
          }}>
            {recoveryCodes.map((code) => <Typography.Text copyable key={code}>{code}</Typography.Text>)}
          </div>
          <Button icon={<CopyOutlined />} onClick={() => void copyText(recoveryCodes.join('\n'))}>
            复制全部恢复码
          </Button>
          <Checkbox checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)}>
            我已把恢复码保存到安全位置
          </Checkbox>
        </Space>
      ) : setup ? (
        <Space direction="vertical" size={14} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="首次登录必须完成此步骤"
            description="用任意身份验证器扫描二维码，然后输入应用中显示的 6 位验证码。"
          />
          <div style={{ display: 'flex', justifyContent: 'center' }}>
            <QRCode value={setup.provisioningUri} size={190} bordered />
          </div>
          <Typography.Text type="secondary">无法扫码时，手动输入密钥：</Typography.Text>
          <Input
            value={setup.secret}
            readOnly
            addonAfter={<Button type="text" size="small" onClick={() => void copyText(setup.secret)}>复制</Button>}
          />
          <Form form={form} layout="vertical" onFinish={confirm}>
            <Form.Item
              name="code"
              label="6 位验证码"
              rules={[
                { required: true, message: '请输入验证码' },
                { pattern: /^\d{6}$/, message: '请输入身份验证器中的 6 位数字' },
              ]}
            >
              <Input
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                placeholder="000000"
                autoFocus
              />
            </Form.Item>
            <Button type="primary" htmlType="submit" loading={confirmLoading} block>
              验证并启用
            </Button>
          </Form>
        </Space>
      ) : (
        <Button onClick={() => void loadSetup()} loading={setupLoading} block>重试</Button>
      )}
    </Modal>
  );
}
