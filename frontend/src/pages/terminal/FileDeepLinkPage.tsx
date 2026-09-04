import { useEffect, useState } from 'react';
import { Alert, Button, Input, Spin, Typography } from 'antd';
import { FileTextOutlined, ReloadOutlined } from '@ant-design/icons';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { terminal } from '../../api/client';
import { useUserAuth } from '../../context/UserAuthContext';
import { workspaceFileDestination } from '../../utils/workspaceFileLinks';

const RETURN_TO_KEY = 'zhuojian_return_to';

/**
 * 永久内部文件地址入口。
 *
 * 未登录时保持完全中性，不查询文件或泄露租户信息；登录后只做一次实时鉴权，
 * 随即进入该身份原本的工作空间页面，由正常工作空间壳层打开统一文件抽屉。
 */
export default function FileDeepLinkPage() {
  const { fileId = '' } = useParams<{ fileId: string }>();
  const [searchParams] = useSearchParams();
  const versionId = searchParams.get('version');
  const navigate = useNavigate();
  const { token: userToken, user } = useUserAuth();
  const [organizationSlug, setOrganizationSlug] = useState(user?.organization_slug || '');
  const [attempt, setAttempt] = useState(0);
  const [accessError, setAccessError] = useState(false);

  useEffect(() => {
    if (userToken) return;
    const returnTo = `/f/${encodeURIComponent(fileId)}${versionId ? `?version=${encodeURIComponent(versionId)}` : ''}`;
    sessionStorage.setItem(RETURN_TO_KEY, returnTo);
  }, [fileId, userToken, versionId]);

  useEffect(() => {
    if (!userToken) return;
    let disposed = false;
    setAccessError(false);

    const resolve = async () => {
      if (!fileId) throw new Error('missing file id');
      const slug = user?.organization_slug;
      if (!slug) throw new Error('missing organization slug');
      const file = await terminal.getWsFile(fileId);
      if (versionId) await terminal.getWsFileVersion(fileId, versionId);
      if (!disposed) {
        navigate(workspaceFileDestination(file, { kind: 'user', organizationSlug: slug }, versionId), { replace: true });
      }
    };

    void resolve().catch(() => {
      if (!disposed) setAccessError(true);
    });
    return () => { disposed = true; };
  }, [attempt, fileId, navigate, user?.organization_slug, userToken, versionId]);

  const openEmployeeLogin = () => {
    const slug = organizationSlug.trim();
    if (!/^[a-z0-9][a-z0-9-]{0,62}$/i.test(slug)) return;
    window.location.assign(`/${encodeURIComponent(slug)}/terminal/login`);
  };

  if (!userToken) {
    const validSlug = /^[a-z0-9][a-z0-9-]{0,62}$/i.test(organizationSlug.trim());
    return (
      <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#f8f9fc' }}>
        <div style={{ width: 'min(420px, 100%)', padding: 28, borderRadius: 16, background: '#fff', boxShadow: '0 16px 48px rgba(15, 23, 42, 0.12)' }}>
          <FileTextOutlined style={{ display: 'block', marginBottom: 14, fontSize: 40, color: '#6366f1' }} />
          <Typography.Title level={3} style={{ margin: 0 }}>打开内部文件</Typography.Title>
          <Typography.Paragraph type="secondary" style={{ marginTop: 10 }}>
            请先登录。系统会在登录后实时校验你的角色权限，不会向未登录用户透露文件或所属企业信息。
          </Typography.Paragraph>
          <Input
            value={organizationSlug}
            onChange={(event) => setOrganizationSlug(event.target.value)}
            onPressEnter={openEmployeeLogin}
            placeholder="企业标识（登录地址中的企业名称）"
            autoComplete="organization"
          />
          <Button type="primary" block style={{ marginTop: 12 }} disabled={!validSlug} onClick={openEmployeeLogin}>
            员工登录并继续
          </Button>
          <Button type="link" block href="/login" style={{ marginTop: 6 }}>
            管理员登录
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', padding: 24, background: '#f8f9fc' }}>
      {accessError ? (
        <div style={{ width: 'min(440px, 100%)' }}>
          <Alert
            type="warning"
            showIcon
            message="文件不存在或没有查看权限"
            description="请确认当前登录身份仍具有该工作空间的查看权限。"
            action={<Button size="small" icon={<ReloadOutlined />} onClick={() => setAttempt((value) => value + 1)}>重试</Button>}
          />
        </div>
      ) : (
        <Spin tip="正在进入对应工作空间…" size="large" />
      )}
    </div>
  );
}

export { RETURN_TO_KEY };
