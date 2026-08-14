import LoginForm, { LoginBackdrop } from '../components/LoginForm';

/** 平台登录页（/login）：root / 平台 admin 等未绑定组织的账号。 */
export default function Login() {
  return (
    <LoginBackdrop>
      <LoginForm />
    </LoginBackdrop>
  );
}
