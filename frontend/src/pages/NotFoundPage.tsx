import { Button, Result } from 'antd';
import { useLocation, useNavigate } from 'react-router-dom';

function homePathFor(pathname: string): string {
  const enterpriseTerminal = pathname.match(/^\/([^/]+)\/terminal(?:\/|$)/);
  if (enterpriseTerminal) return `/${enterpriseTerminal[1]}/terminal`;
  if (/^\/terminal(?:\/|$)/.test(pathname)) return '/terminal';
  return '/monitor/router';
}

export default function NotFoundPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const homePath = homePathFor(location.pathname);

  return (
    <div style={{ minHeight: '100%', display: 'grid', placeItems: 'center', background: '#fff' }}>
      <Result
        status="404"
        title="页面不存在"
        subTitle="这个地址不存在，或者对应功能已经下线。"
        extra={<Button type="primary" onClick={() => navigate(homePath, { replace: true })}>返回可用页面</Button>}
      />
    </div>
  );
}
