import { useEffect, useState } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { Alert, Button, Spin, Form, Input, message } from 'antd';
import { LockOutlined, UserOutlined, ApartmentOutlined } from '@ant-design/icons';
import { LoginBackdrop, LoginCard } from '../../components/LoginForm';
import ContactUs from '../../components/ContactUs';
import { WB, FS } from '../../components/finder/theme';
import { auth as authApi, terminal, type OrgInfo } from '../../api/client';
import { useUserAuth, type TerminalUserState } from '../../context/UserAuthContext';
import { BRAND_LOGO_SLOTS, applyBrandFavicon } from '../../branding/BrandLogoSlot';
import { BRAND_TITLES, useBrandTitle } from '../../branding/brand';

/**
 * 终端用户登录页（/{slug}/terminal/login）：组织员工经 slug 登录，进入灼见。
 * 进入时按 slug 公开查询组织名展示在登录框上方；登录成功后跳转 /{slug}/terminal。
 */
export default function UserLoginPage() {
  useBrandTitle(BRAND_TITLES.terminal);

  const { slug = '' } = useParams<{ slug: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const { login } = useUserAuth();
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pendingPasswordChange, setPendingPasswordChange] = useState<{
    token: string;
    oldPassword: string;
    user: TerminalUserState;
    canonicalSlug: string;
  } | null>(null);

  // BRAND_LOGO_SLOT: 用户登录页也使用用户端浏览器标签图标位。
  useEffect(() => applyBrandFavicon(BRAND_LOGO_SLOTS.terminalFavicon), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    authApi.orgInfo(slug)
      .then((info) => {
        if (cancelled) return;
        setOrg(info);
        if (info.slug !== slug) {
          navigate({
            pathname: `/${info.slug}${location.pathname.slice(slug.length + 1)}`,
            search: location.search,
            hash: location.hash,
          }, { replace: true });
        }
      })
      .catch(() => { if (!cancelled) setNotFound(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [location.hash, location.pathname, location.search, navigate, slug]);

  const completeLogin = (token: string, userState: TerminalUserState, canonicalSlug: string) => {
    login(token, userState);
    const pending = sessionStorage.getItem('zhuojian_return_to') || '';
    if (/^\/f\/[0-9a-f-]{36}(?:\?version=[^#\s]+)?$/i.test(pending)) {
      sessionStorage.removeItem('zhuojian_return_to');
      navigate(pending);
    } else {
      navigate(`/${canonicalSlug}/terminal`);
    }
  };

  const onFinish = async (values: { username: string; password: string }) => {
    setSubmitting(true);
    try {
      const canonicalSlug = org?.slug || slug;
      const data = await terminal.loginBySlug(canonicalSlug, values.username, values.password);
      const userState: TerminalUserState = {
        id: data.user.id,
        username: data.user.username,
        display_name: data.user.display_name,
        role: data.user.role,
        organization_id: data.user.organization_id,
        organization_slug: canonicalSlug,
        organization_name: org?.name ?? canonicalSlug,
        department_ids: data.user.department_ids ?? (data.user.department_id ? [data.user.department_id] : []),
        department_id: data.user.department_id,
        team_id: data.user.team_id,
      };
      if (data.must_change_password) {
        setPendingPasswordChange({
          token: data.access_token,
          oldPassword: values.password,
          user: userState,
          canonicalSlug,
        });
        return;
      }
      completeLogin(data.access_token, userState, canonicalSlug);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '登录失败');
    } finally {
      setSubmitting(false);
    }
  };

  const onChangePassword = async (values: { newPassword: string }) => {
    if (!pendingPasswordChange) return;
    setSubmitting(true);
    try {
      const data = await terminal.changeOwnPassword(
        pendingPasswordChange.token,
        pendingPasswordChange.oldPassword,
        values.newPassword,
      );
      message.success('密码已更新，请妥善保管');
      completeLogin(data.access_token, pendingPasswordChange.user, pendingPasswordChange.canonicalSlug);
    } catch (err) {
      message.error(err instanceof Error ? err.message : '密码修改失败');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <LoginBackdrop>
      {loading ? (
        <Spin size="large" style={{ position: 'relative', zIndex: 1 }} />
      ) : notFound ? (
        <Alert
          type="error" showIcon
          style={{ position: 'relative', zIndex: 1, maxWidth: 380, borderRadius: 12 }}
          message={`组织「${slug}」不存在`}
          description="请确认登录地址中的组织标识是否正确。"
          action={<Button type="primary" size="small" href="/login">平台登录</Button>}
        />
      ) : (
        <LoginCard
          logoSlot={BRAND_LOGO_SLOTS.terminalLogin}
          title={
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
              <ApartmentOutlined style={{ color: WB.primary, fontSize: FS.body }} />
              {org?.name || org?.slug || slug}
            </span>
          }
          subtitle={BRAND_TITLES.terminal}
        >
          {pendingPasswordChange ? (
            <Form name="user-change-password" onFinish={onChangePassword} autoComplete="off">
              <Alert
                showIcon
                type="warning"
                message="首次登录需要设置自己的密码"
                description="完成后即可进入系统并连接个人 AI 助手。"
                style={{ marginBottom: 18 }}
              />
              <Form.Item
                name="newPassword"
                rules={[
                  { required: true, message: '请输入新密码' },
                  { min: 8, message: '密码至少 8 个字符' },
                ]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="新密码（至少 8 个字符）" autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="confirmPassword"
                dependencies={['newPassword']}
                rules={[
                  { required: true, message: '请再次输入新密码' },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      return !value || getFieldValue('newPassword') === value
                        ? Promise.resolve()
                        : Promise.reject(new Error('两次输入的密码不一致'));
                    },
                  }),
                ]}
              >
                <Input.Password prefix={<LockOutlined />} placeholder="再次输入新密码" autoComplete="new-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={submitting} block>保存并进入</Button>
            </Form>
          ) : <Form name="user-login" onFinish={onFinish} autoComplete="off">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined />} placeholder="密码" autoComplete="current-password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <Button type="primary" htmlType="submit" loading={submitting} style={{ flex: 1 }}>登 录</Button>
                <ContactUs slug={org?.slug || slug} />
              </div>
            </Form.Item>
          </Form>}
        </LoginCard>
      )}
    </LoginBackdrop>
  );
}
