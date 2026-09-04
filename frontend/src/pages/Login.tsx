import LoginForm, { LoginBackdrop } from '../components/LoginForm';
import { BRAND_TITLES, useBrandTitle } from '../branding/brand';
import { Spin } from 'antd';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

/** 平台登录页（/login）：仅供 platform_super_admin 使用。 */
export default function Login() {
  useBrandTitle(BRAND_TITLES.platform);
  const { status } = useAuth();

  if (status === 'authenticated') return <Navigate to="/monitor/router" replace />;

  return (
    <LoginBackdrop>
      {status === 'loading' || status === 'mfa_enrollment_required' ? <Spin size="large" /> : <LoginForm />}
    </LoginBackdrop>
  );
}
