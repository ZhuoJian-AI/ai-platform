import LoginForm, { LoginBackdrop } from '../components/LoginForm';
import { BRAND_TITLES, useBrandTitle } from '../branding/brand';

/** 平台登录页（/login）：root / 平台 admin 等未绑定组织的账号。 */
export default function Login() {
  useBrandTitle(BRAND_TITLES.platform);

  return (
    <LoginBackdrop>
      <LoginForm />
    </LoginBackdrop>
  );
}
