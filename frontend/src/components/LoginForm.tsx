import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Form, Input, Button, Card, ConfigProvider, Alert, Modal } from 'antd';
import { LockOutlined, UserOutlined, ApartmentOutlined } from '@ant-design/icons';
import { useAuth } from '../context/AuthContext';
import type { AdminUser } from '../context/AuthContext';
import { WB, WB_FONT, FS, antdTheme } from './finder/theme';
import ContactUs from './ContactUs';
import BrandLogoSlot, { BRAND_LOGO_SLOTS, type BrandLogoSlotId } from '../branding/BrandLogoSlot';
import { BRAND_TITLES } from '../branding/brand';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const RETURN_TO_KEY = 'zhuojian_return_to';

function postLoginPath(fallback: string): string {
  const pending = sessionStorage.getItem(RETURN_TO_KEY) || '';
  if (!/^\/f\/[0-9a-f-]{36}(?:\?version=[^#\s]+)?$/i.test(pending)) return fallback;
  sessionStorage.removeItem(RETURN_TO_KEY);
  return pending;
}

interface LoginFormProps {
  /** 组织门户登录时传入 slug；平台登录不传。 */
  slug?: string;
  /** 组织名（slug 对应），展示在登录框上方。仅 slug 存在时有意义。 */
  orgName?: string;
}

/**
 * 登录卡片（平台 / 组织门户共用）。
 * - 不带 slug：平台登录（/login），匹配未绑定组织的平台级账号。
 * - 带 slug：组织门户登录（/{slug}/login），匹配该组织下的 org_admin。
 */
export default function LoginForm({ slug, orgName }: LoginFormProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [mustChangePwd, setMustChangePwd] = useState(false);
  const [loggedInToken, setLoggedInToken] = useState('');
  const [loggedInAdmin, setLoggedInAdmin] = useState<AdminUser | null>(null);
  const [newPwdForm] = Form.useForm();
  const { login } = useAuth();
  const navigate = useNavigate();

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true);
    setError('');
    try {
      const resp = await fetch(`${BASE_URL}/api/v1/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug, username: values.username, password: values.password }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || '登录失败');
      }
      const data = await resp.json();

      // 首次登录需要强制修改密码
      if (data.must_change_password) {
        setMustChangePwd(true);
        setLoggedInToken(data.access_token);
        setLoggedInAdmin(data.admin as AdminUser);
        return;
      }

      login(data.access_token, data.admin as AdminUser);
      navigate(postLoginPath('/monitor/router'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
    } finally {
      setLoading(false);
    }
  };

  const handleChangePassword = async (values: { newPassword: string }) => {
    try {
      const resp = await fetch(`${BASE_URL}/api/v1/auth/change-password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${loggedInToken}`,
        },
        body: JSON.stringify({
          old_password: 'root',  // 默认旧密码
          new_password: values.newPassword,
        }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}));
        throw new Error(body.detail || '修改密码失败');
      }
      // 修改成功，重新登录
      setMustChangePwd(false);
      if (loggedInAdmin) {
        login(loggedInToken, { ...loggedInAdmin, must_change_password: false });
      }
      navigate(postLoginPath('/monitor/router'));
    } catch (err) {
      setError(err instanceof Error ? err.message : '未知错误');
    }
  };

  const title = slug ? (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
      <ApartmentOutlined style={{ color: WB.primary, fontSize: FS.body }} />
      {orgName || slug}
    </span>
  ) : undefined;
  const subtitle = slug ? BRAND_TITLES.organization : BRAND_TITLES.platform;

  return (
    <>
      <LoginCard
        title={title}
        subtitle={subtitle}
        logoSlot={slug ? BRAND_LOGO_SLOTS.organizationLogin : BRAND_LOGO_SLOTS.platformLogin}
      >
        {error && (
          <Alert
            type="error"
            message={error}
            showIcon
            closable
            onClose={() => setError('')}
            style={{ marginBottom: 14 }}
          />
        )}

        <Form name="login" onFinish={onFinish} autoComplete="off">
          <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
            <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
          </Form.Item>
          <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
            <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <Button type="primary" htmlType="submit" loading={loading} style={{ flex: 1 }}>登 录</Button>
              <ContactUs slug={slug} />
            </div>
          </Form.Item>
        </Form>
      </LoginCard>

      {/* 强制修改密码弹窗 */}
      <Modal
        title="⚠️ 首次登录 — 请修改默认密码"
        open={mustChangePwd}
        closable={false}
        maskClosable={false}
        okText="确认修改"
        onOk={() => newPwdForm.submit()}
      >
        <Alert type="warning" message="检测到您使用的是默认密码，请立即修改以确保安全" style={{ marginBottom: 16 }} />
        <Form form={newPwdForm} layout="vertical" onFinish={handleChangePassword}>
          <Form.Item
            name="newPassword"
            label="新密码"
            rules={[
              { required: true, min: 4, message: '请输入新密码（至少4位）' },
            ]}
          >
            <Input.Password placeholder="请输入新密码" autoFocus />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label="确认密码"
            dependencies={['newPassword']}
            rules={[
              { required: true, message: '请确认密码' },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue('newPassword') === value) return Promise.resolve();
                  return Promise.reject(new Error('两次输入不一致'));
                },
              }),
            ]}
          >
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}

/**
 * 登录卡片 chrome：白底浅边、WB_FONT、字号梯与功能页一致（标题 14 / 辅助 12）。
 * 平台登录、组织门户、终端用户登录共用，保证三处卡片视觉与字体完全统一。
 */
export function LoginCard({
  title,
  subtitle,
  logoSlot = BRAND_LOGO_SLOTS.platformLogin,
  children,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  /** BRAND_LOGO_SLOT: 登录卡片顶部企业品牌位。 */
  logoSlot?: BrandLogoSlotId;
  children: React.ReactNode;
}) {
  return (
    <Card
      style={{
        width: 380,
        borderRadius: 12,
        position: 'relative',
        zIndex: 1,
        background: '#fff',
        border: `1px solid ${WB.border}`,
        boxShadow: '0 4px 24px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)',
        animation: 'loginCardFade 0.5s cubic-bezier(0.22,1,0.36,1) both',
      }}
      styles={{ body: { padding: 28 } }}
    >
      <div style={{ textAlign: 'center', marginBottom: 24 }}>
        <BrandLogoSlot
          slot={logoSlot}
          width={200}
          height={56}
          style={{ margin: '0 auto 12px' }}
        />
        {title && (
          <div style={{ fontSize: FS.title, fontWeight: 600, color: WB.text, lineHeight: 1.4 }}>{title}</div>
        )}
        {subtitle && (
          <div style={{ fontSize: FS.aux, color: WB.textAux, marginTop: 4 }}>{subtitle}</div>
        )}
      </div>
      {children}
    </Card>
  );
}

/**
 * 登录页公共背景层（浅色 macOS 风 + 主题注入）。
 * 包裹 ConfigProvider(antdTheme)，让登录页 antd 组件与功能页同款：字号 13、控件高 28、
 * 主色 #6366F1、圆角 6–8——登录路由在 App 顶层、未走 AppLayout 的 ConfigProvider，
 * 故在此显式注入。平台 / 组织门户 / 终端用户登录共用。
 */
export function LoginBackdrop({ children }: { children: React.ReactNode }) {
  return (
    <ConfigProvider theme={antdTheme}>
      <div
        className="login-backdrop"
        style={{
          minHeight: '100vh',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          position: 'relative',
          overflow: 'hidden',
          fontFamily: WB_FONT,
          background:
            'radial-gradient(circle at 25% 18%, #e0e7ff 0%, transparent 45%), radial-gradient(circle at 78% 82%, #f3e8ff 0%, transparent 42%), #f5f5f7',
          backgroundSize: '220% 220%',
          animation: 'loginBgShift 12s ease-in-out infinite',
        }}
      >
        <style>{`
          @keyframes loginCardFade {
            0%   { opacity: 0; transform: translateY(12px); }
            100% { opacity: 1; transform: translateY(0); }
          }
          @keyframes loginBgShift {
            0%   { background-position: 0% 50%; }
            50%  { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
          }
          @keyframes loginFloatA {
            0%   { transform: translate(0, 0) scale(1); }
            25%  { transform: translate(160px, -110px) scale(1.18); }
            50%  { transform: translate(80px, 120px) scale(0.92); }
            75%  { transform: translate(-120px, -40px) scale(1.1); }
            100% { transform: translate(0, 0) scale(1); }
          }
          @keyframes loginFloatB {
            0%   { transform: translate(0, 0) scale(1); }
            25%  { transform: translate(-170px, 120px) scale(1.15); }
            50%  { transform: translate(-70px, -130px) scale(0.9); }
            75%  { transform: translate(130px, 60px) scale(1.12); }
            100% { transform: translate(0, 0) scale(1); }
          }
          @keyframes loginFloatC {
            0%   { transform: translate(0, 0) scale(1); }
            33%  { transform: translate(120px, 100px) scale(1.2); }
            66%  { transform: translate(-110px, -90px) scale(0.88); }
            100% { transform: translate(0, 0) scale(1); }
          }
          @media (prefers-reduced-motion: reduce) {
            .login-blob, .login-backdrop { animation: none !important; }
          }
        `}</style>

        {/* 光晕（主色染，呼应功能页 indigo 主色；明显漂浮位移） */}
        <div className="login-blob" style={{ position: 'absolute', width: 420, height: 420, borderRadius: '50%', top: '-10%', left: '-8%', background: 'radial-gradient(circle, rgba(99,102,241,0.42) 0%, rgba(99,102,241,0.18) 45%, transparent 75%)', filter: 'blur(8px)', animation: 'loginFloatA 9s ease-in-out infinite' }} />
        <div className="login-blob" style={{ position: 'absolute', width: 460, height: 460, borderRadius: '50%', bottom: '-14%', right: '-10%', background: 'radial-gradient(circle, rgba(124,58,237,0.38) 0%, rgba(124,58,237,0.16) 45%, transparent 75%)', filter: 'blur(10px)', animation: 'loginFloatB 11s ease-in-out infinite' }} />
        <div className="login-blob" style={{ position: 'absolute', width: 320, height: 320, borderRadius: '50%', top: '38%', left: '50%', background: 'radial-gradient(circle, rgba(56,189,248,0.34) 0%, rgba(56,189,248,0.14) 45%, transparent 75%)', filter: 'blur(8px)', animation: 'loginFloatC 13s ease-in-out infinite' }} />

        {children}
      </div>
    </ConfigProvider>
  );
}
