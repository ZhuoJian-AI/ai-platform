import { useEffect, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Alert, Button, Spin } from 'antd';
import LoginForm, { LoginBackdrop } from '../components/LoginForm';
import { auth as authApi, type OrgInfo } from '../api/client';
import { BRAND_TITLES, useBrandTitle } from '../branding/brand';

/**
 * 组织门户登录页（/{slug}/login）：org_admin 通过所属组织的 slug 登录。
 * 进入时按 slug 公开查询组织名并展示在登录框上方；slug 无效则提示。
 */
export default function OrgLogin() {
  useBrandTitle(BRAND_TITLES.organization);

  const { slug = '' } = useParams<{ slug: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

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

  return (
    <LoginBackdrop>
      {loading ? (
        <Spin size="large" style={{ position: 'relative', zIndex: 1 }} />
      ) : notFound ? (
        <Alert
          type="error"
          showIcon
          style={{ position: 'relative', zIndex: 1, maxWidth: 380, borderRadius: 12 }}
          message={`组织「${slug}」不存在`}
          description="请确认登录地址中的组织标识是否正确。如需平台管理，请前往平台登录页。"
          action={<Button type="primary" size="small" href="/login">平台登录</Button>}
        />
      ) : (
        <LoginForm slug={org?.slug || slug} orgName={org?.name} />
      )}
    </LoginBackdrop>
  );
}
