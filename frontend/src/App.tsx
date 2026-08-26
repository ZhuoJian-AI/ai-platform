import { useState, useEffect, type CSSProperties, type ReactNode } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Drawer, ConfigProvider, Avatar, Popover, Button } from 'antd';
import {
  ApartmentOutlined, KeyOutlined, CloudServerOutlined,
  SafetyOutlined, TeamOutlined,
  LogoutOutlined, ToolOutlined, MonitorOutlined, RobotOutlined, UserOutlined,
  FolderOpenOutlined, ExperimentOutlined, DatabaseOutlined, PartitionOutlined,
  ApiOutlined, BarChartOutlined, QuestionCircleOutlined, ReadOutlined,
  MoreOutlined, PhoneOutlined,
  AppstoreAddOutlined, DeploymentUnitOutlined, ShopOutlined, HistoryOutlined,
  AppstoreOutlined, LinkOutlined, SettingOutlined, RightOutlined, DownOutlined,
} from '@ant-design/icons';
import { WB, WB_FONT, FS, antdTheme } from './components/finder/theme';
import { AuthProvider, useAuth, RequireAuth } from './context/AuthContext';
import { UserAuthProvider, UserRequireAuth } from './context/UserAuthContext';
import HelpBody from './components/HelpDrawer';
import Login from './pages/Login';
import OrgLogin from './pages/OrgLogin';
import UserLoginPage from './pages/terminal/UserLoginPage';
import Terminal from './pages/terminal/Terminal';
import Organizations from './pages/Organizations';
import ContactInfo from './pages/ContactInfo';
import ApiKeys from './pages/ApiKeys';
import LlmProviders from './pages/LlmProviders';
import DlpRules from './pages/DlpRules';
import AdminManagement from './pages/AdminManagement';
import UsersPage from './pages/org/Users';
import Workspaces from './pages/agent/Workspaces';
import Agents from './pages/agent/Agents';
import AgentPlayground from './pages/agent/AgentPlayground';
import Rag from './pages/agent/Rag';
import Judges from './pages/agent/Judges';
import MemoryPage from './pages/agent/Memory';
import Connectors from './pages/tools/Connectors';
import DataInterfaces from './pages/tools/DataInterfaces';
import Skills from './pages/tools/Skills';
import OntologyPage from './pages/tools/Ontology';
import MonitorOverview from './pages/monitor/MonitorOverview';
import RouterMonitor from './pages/monitor/RouterMonitor';
import AgentMonitor from './pages/monitor/AgentMonitor';
import ToolMonitor from './pages/monitor/ToolMonitor';
import BrandLogoSlot, { BRAND_LOGO_SLOTS, applyBrandFavicon } from './branding/BrandLogoSlot';
import { BRAND_TITLES, useBrandTitle } from './branding/brand';
import PlatformExtensions from './pages/platform/PlatformExtensions';
import EnterpriseApplications from './pages/apps/EnterpriseApplications';
import EnterpriseApplicationDetail from './pages/apps/EnterpriseApplicationDetail';

interface MenuEntry {
  path: string;
  label: string;
  icon: ReactNode;
  superOnly?: boolean;
  /** 二期开发内容：隐藏于二级菜单，路由保留以便后续启用 */
  hidden?: boolean;
}

interface Subsystem {
  key: string;
  label: string;
  icon: ReactNode;
  built: boolean;
  menu: MenuEntry[];
  /** path → element；仅 built 子系统使用 */
  routes?: { path: string; element: ReactNode; superOnly?: boolean }[];
}

/** 一级菜单：ai_infra 平台五个子系统。built 标识是否已实现页面。 */
const SUBSYSTEMS: Subsystem[] = [
  {
    key: 'org_mgmt', label: '组织管理', icon: <ApartmentOutlined />, built: true,
    menu: [
      { path: '/org/structure', label: '组织架构', icon: <ApartmentOutlined /> },
      { path: '/org/admins', label: '管理员管理', icon: <TeamOutlined />, superOnly: true },
      { path: '/org/users', label: '用户管理', icon: <UserOutlined /> },
      { path: '/org/contact', label: '联系方式', icon: <PhoneOutlined /> },
    ],
    routes: [
      { path: '/org/structure', element: <Organizations /> },
      { path: '/org/admins', element: <AdminManagement /> },
      { path: '/org/users', element: <UsersPage /> },
      { path: '/org/contact', element: <ContactInfo /> },
    ],
  },
  {
    key: 'llm_router', label: '模型路由器', icon: <CloudServerOutlined />, built: true,
    menu: [
      { path: '/keys', label: 'API Key 管理', icon: <KeyOutlined /> },
      { path: '/providers', label: '模型提供商', icon: <CloudServerOutlined /> },
      { path: '/dlp', label: '安全围栏', icon: <SafetyOutlined /> },
    ],
    routes: [
      { path: '/keys', element: <ApiKeys /> },
      { path: '/providers', element: <LlmProviders /> },
      { path: '/dlp', element: <DlpRules /> },
    ],
  },
  {
    key: 'agent_platform', label: '智能体平台', icon: <RobotOutlined />, built: true,
    menu: [
      { path: '/agent/workspaces', label: '工作空间', icon: <FolderOpenOutlined /> },
      { path: '/agent/agents', label: '智能体', icon: <RobotOutlined /> },
      // 以下两项为二期开发内容，暂时隐藏于二级菜单（路由保留以便后续启用）
      { path: '/agent/playground', label: '测试广场', icon: <ExperimentOutlined />, hidden: true },
      { path: '/agent/rag', label: 'RAG知识库', icon: <DatabaseOutlined /> },
      { path: '/agent/judges', label: 'Judge 模板', icon: <SafetyOutlined />, hidden: true },
      { path: '/agent/memory', label: '长期记忆', icon: <ReadOutlined /> },
    ],
    routes: [
      { path: '/agent/workspaces', element: <Workspaces /> },
      { path: '/agent/agents', element: <Agents /> },
      { path: '/agent/playground', element: <AgentPlayground /> },
      { path: '/agent/rag', element: <Rag /> },
      { path: '/agent/judges', element: <Judges /> },
      { path: '/agent/memory', element: <MemoryPage /> },
    ],
  },
  {
    key: 'tool_connector', label: '工具连接器', icon: <ToolOutlined />, built: true,
    menu: [
      { path: '/tools/connectors', label: '连接器', icon: <ApiOutlined /> },
      { path: '/tools/data-interfaces', label: '数据接口', icon: <ApiOutlined /> },
      { path: '/tools/skills', label: '技能', icon: <ToolOutlined /> },
      { path: '/tools/ontology', label: '本体', icon: <PartitionOutlined /> },
    ],
    routes: [
      { path: '/tools/connectors', element: <Connectors /> },
      { path: '/tools/data-interfaces', element: <DataInterfaces /> },
      { path: '/tools/skills', element: <Skills /> },
      { path: '/tools/ontology', element: <OntologyPage /> },
    ],
  },
  {
    key: 'enterprise_apps', label: '企业应用', icon: <AppstoreOutlined />, built: true,
    menu: [
      { path: '/enterprise-apps', label: '应用管理', icon: <AppstoreOutlined /> },
      { path: '/enterprise-apps/navigation', label: '导航配置', icon: <SettingOutlined /> },
      { path: '/enterprise-apps/permissions', label: '应用权限', icon: <SafetyOutlined /> },
      { path: '/enterprise-apps/assistant', label: '业务助手', icon: <LinkOutlined /> },
    ],
    routes: [
      { path: '/enterprise-apps', element: <EnterpriseApplications section="applications" /> },
      { path: '/enterprise-apps/:appId', element: <EnterpriseApplicationDetail /> },
      { path: '/enterprise-apps/navigation', element: <EnterpriseApplications section="navigation" /> },
      { path: '/enterprise-apps/permissions', element: <EnterpriseApplications section="permissions" /> },
      { path: '/enterprise-apps/assistant', element: <EnterpriseApplications section="assistant" /> },
    ],
  },
  {
    key: 'platform_extensions', label: '平台扩展', icon: <AppstoreAddOutlined />, built: true,
    menu: [
      { path: '/platform/extensions', label: '扩展总览', icon: <AppstoreAddOutlined />, superOnly: true },
      { path: '/platform/extensions/runtime', label: 'Runtime 管理', icon: <DeploymentUnitOutlined />, superOnly: true },
      { path: '/platform/extensions/tools', label: '系统工具', icon: <ToolOutlined />, superOnly: true },
      { path: '/platform/extensions/catalog', label: '插件仓库', icon: <ShopOutlined />, superOnly: true },
      { path: '/platform/extensions/releases', label: '发布与回滚', icon: <HistoryOutlined />, superOnly: true },
    ],
    routes: [
      { path: '/platform/extensions', element: <PlatformExtensions section="overview" />, superOnly: true },
      { path: '/platform/extensions/runtime', element: <PlatformExtensions section="runtime" />, superOnly: true },
      { path: '/platform/extensions/tools', element: <PlatformExtensions section="tools" />, superOnly: true },
      { path: '/platform/extensions/catalog', element: <PlatformExtensions section="catalog" />, superOnly: true },
      { path: '/platform/extensions/releases', element: <PlatformExtensions section="releases" />, superOnly: true },
    ],
  },
  {
    key: 'app_monitor', label: '应用监控台', icon: <MonitorOutlined />, built: true,
    menu: [
      { path: '/monitor/overview', label: '总览', icon: <BarChartOutlined /> },
      { path: '/monitor/router', label: '路由器监控', icon: <CloudServerOutlined /> },
      { path: '/monitor/agents', label: '智能体监控', icon: <RobotOutlined /> },
      { path: '/monitor/tools', label: '工具监控', icon: <ToolOutlined /> },
    ],
    routes: [
      { path: '/monitor/overview', element: <MonitorOverview /> },
      { path: '/monitor/router', element: <RouterMonitor /> },
      { path: '/monitor/agents', element: <AgentMonitor /> },
      { path: '/monitor/tools', element: <ToolMonitor /> },
    ],
  },
];

function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const { admin, logout, isSuperAdmin, isOrgScoped } = useAuth();
  const [helpOpen, setHelpOpen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set(
    SUBSYSTEMS.filter((subsystem) => subsystem.built).map((subsystem) => subsystem.key),
  ));

  useBrandTitle(isOrgScoped() ? BRAND_TITLES.organization : BRAND_TITLES.platform);

  // BRAND_LOGO_SLOT: 管理端浏览器标签图标。
  useEffect(() => {
    return applyBrandFavicon(BRAND_LOGO_SLOTS.platformFavicon);
  }, []);

  useEffect(() => {
    const active = SUBSYSTEMS.find((subsystem) => subsystem.menu.some((item) => item.path === location.pathname));
    if (active) setExpandedGroups((current) => current.has(active.key) ? current : new Set([...current, active.key]));
  }, [location.pathname]);

  const ROLE_LABELS: Record<string, string> = { super_admin: '超管', admin: '管理员', org_admin: '组织管理员' };

  // 扁平渲染全部已建成子系统的路由——单侧栏全路由可见，直达链接不再被重定向回首页
  // （原 activeSubsystem 状态不随 URL 同步的坑由此彻底移除）
  const allRoutes = SUBSYSTEMS.filter((s) => s.built)
    .flatMap((s) => s.routes ?? [])
    .filter((route) => !route.superOnly || isSuperAdmin());

  const navItemStyle = (active: boolean): CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', borderRadius: 6,
    cursor: 'pointer', fontSize: FS.body, lineHeight: 1, userSelect: 'none', margin: '1px 6px',
    background: active ? `${WB.primary}1A` : undefined,
    color: active ? WB.primary : '#4b5563', fontWeight: active ? 600 : 400,
  });

  const userInitial = (admin?.display_name || admin?.username || '?').slice(0, 1).toUpperCase();

  return (
    <ConfigProvider theme={antdTheme}>
      <div style={{ height: '100vh', display: 'flex', fontFamily: WB_FONT, background: '#f5f5f5' }}>
        {/* 左侧栏：终端式单栏（品牌 / 分组导航 / 底部用户） */}
        <aside style={{ width: 220, background: WB.sidebar, borderRight: `1px solid ${WB.border}`, display: 'flex', flexDirection: 'column', flex: '0 0 auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 16px', flex: '0 0 auto' }}>
            <BrandLogoSlot
              slot={BRAND_LOGO_SLOTS.adminSidebar}
              width="100%"
              height={26}
              style={{ maxWidth: 188 }}
            />
          </div>

          <nav style={{ flex: 1, overflowY: 'auto', padding: '4px 0 8px' }} className="wb-scroll-hide">
            {SUBSYSTEMS.filter((s) => s.built).map((s) => {
              const items = s.menu.filter((m) => !m.hidden && (!m.superOnly || isSuperAdmin()));
              if (items.length === 0) return null;
              const expanded = expandedGroups.has(s.key);
              return (
                <div key={s.key} style={{ marginBottom: 6 }}>
                  <div
                    onClick={() => setExpandedGroups((current) => {
                      const next = new Set(current);
                      if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
                      return next;
                    })}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: FS.micro, fontWeight: 600, color: WB.textAux, letterSpacing: 0.4, textTransform: 'uppercase', padding: '8px 14px 4px 18px', userSelect: 'none' }}
                  >
                    <span style={{ display: 'inline-flex', fontSize: 10 }}>{expanded ? <DownOutlined /> : <RightOutlined />}</span>
                    <span>{s.label}</span>
                  </div>
                  {expanded && items.map((m) => {
                    const active = location.pathname === m.path;
                    return (
                      <div
                        key={m.path}
                        onClick={() => navigate(m.path)}
                        style={navItemStyle(active)}
                        onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                        onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                      >
                        <span style={{ fontSize: 16, display: 'inline-flex', color: active ? WB.primary : WB.textAux }}>{m.icon}</span>
                        <span>{m.label}</span>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </nav>

          <div style={{ padding: 10, borderTop: `1px solid ${WB.border}`, flex: '0 0 auto' }}>
            <Popover
              trigger="click"
              placement="topLeft"
              content={
                <div style={{ minWidth: 180 }}>
                  <div style={{ fontSize: FS.aux, color: WB.text, marginBottom: 2 }}>
                    {admin?.display_name || admin?.username}
                  </div>
                  <div style={{ fontSize: FS.micro, color: WB.textAux, marginBottom: 8 }}>
                    [{ROLE_LABELS[admin?.role || ''] || admin?.role}]
                    {isOrgScoped() && admin?.organization_name ? ` · ${admin.organization_name}` : ''}
                  </div>
                  <Button block icon={<QuestionCircleOutlined />} style={{ marginBottom: 6 }} onClick={() => setHelpOpen(true)}>帮助文档</Button>
                  <Button danger block icon={<LogoutOutlined />} onClick={logout}>退出登录</Button>
                </div>
              }
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', padding: '2px 4px', borderRadius: 6 }}>
                <Avatar size={28} style={{ background: 'linear-gradient(135deg, #6366F1 0%, #818CF8 100%)', flex: '0 0 auto' }}>{userInitial}</Avatar>
                <span style={{ fontSize: FS.body, color: WB.text, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {admin?.display_name || admin?.username}
                </span>
                <MoreOutlined style={{ color: WB.textAux }} />
              </div>
            </Popover>
          </div>
        </aside>

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', minWidth: 0 }}>
          <Routes>
            {allRoutes.map((r) => (
              <Route key={r.path} path={r.path} element={r.element} />
            ))}
            <Route path="/*" element={<Navigate to="/monitor/router" replace />} />
          </Routes>
        </main>

        <Drawer
          placement="right"
          open={helpOpen}
          onClose={() => setHelpOpen(false)}
          width={720}
          title={<span><QuestionCircleOutlined style={{ color: WB.primary, marginRight: 6 }} />帮助文档</span>}
          styles={{ header: { borderBottom: `1px solid ${WB.border}`, marginBottom: 0 }, body: { padding: '18px 20px', background: '#fafafa' } }}
        >
          <HelpBody />
        </Drawer>
      </div>
    </ConfigProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/:slug/login" element={<OrgLogin />} />
        {/* 终端用户门户（独立 shell，用户 JWT） */}
        <Route path="/:slug/terminal/login" element={
          <UserAuthProvider><UserLoginPage /></UserAuthProvider>
        } />
        <Route path="/:slug/terminal" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/terminal" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/*" element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        } />
      </Routes>
    </AuthProvider>
  );
}
