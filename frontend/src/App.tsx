import { useState, useEffect, useRef, type CSSProperties, type ReactNode } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { Drawer, ConfigProvider, Avatar, Popover, Button } from 'antd';
import {
  ApartmentOutlined, KeyOutlined, CloudServerOutlined,
  SafetyOutlined, TeamOutlined,
  LogoutOutlined, ToolOutlined, MonitorOutlined, RobotOutlined, UserOutlined,
  FolderOpenOutlined, DatabaseOutlined,
  BarChartOutlined, QuestionCircleOutlined, ReadOutlined,
  MoreOutlined, PhoneOutlined,
  AudioOutlined,
  AppstoreOutlined, LinkOutlined, SettingOutlined, RightOutlined, DownOutlined,
  MenuOutlined, CloseOutlined,
} from '@ant-design/icons';
import { WB, WB_FONT, FS, antdTheme } from './components/finder/theme';
import { AuthProvider, useAuth, RequireAuth } from './context/AuthContext';
import { UserAuthProvider, UserRequireAuth } from './context/UserAuthContext';
import HelpBody from './components/HelpDrawer';
import Login from './pages/Login';
import OrgLogin from './pages/OrgLogin';
import UserLoginPage from './pages/terminal/UserLoginPage';
import Terminal from './pages/terminal/Terminal';
import FileDeepLinkPage from './pages/terminal/FileDeepLinkPage';
import Organizations from './pages/Organizations';
import ContactInfo from './pages/ContactInfo';
import EnterpriseProfile from './pages/org/EnterpriseProfile';
import ApiKeys from './pages/ApiKeys';
import LlmProviders from './pages/LlmProviders';
import DlpRules from './pages/DlpRules';
import AdminManagement from './pages/AdminManagement';
import UsersPage from './pages/org/Users';
import RolesPage from './pages/org/Roles';
import VoicesPage from './pages/org/Voices';
import Workspaces from './pages/agent/Workspaces';
import Agents from './pages/agent/Agents';
import Rag from './pages/agent/Rag';
import MemoryPage from './pages/agent/Memory';
import Skills from './pages/tools/Skills';
import MonitorOverview from './pages/monitor/MonitorOverview';
import RouterMonitor from './pages/monitor/RouterMonitor';
import AgentMonitor from './pages/monitor/AgentMonitor';
import ToolMonitor from './pages/monitor/ToolMonitor';
import BrandLogoSlot, { BRAND_LOGO_SLOTS, applyBrandFavicon } from './branding/BrandLogoSlot';
import { BRAND_TITLES, useBrandTitle } from './branding/brand';
import EnterpriseApplications from './pages/apps/EnterpriseApplications';
import EnterpriseApplicationDetail from './pages/apps/EnterpriseApplicationDetail';
import EnterpriseAccessControl from './pages/apps/EnterpriseAccessControl';
import { useMobileBackDismiss, useResponsiveLayout } from './hooks/useResponsiveLayout';

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

/** 一级菜单：按管理员真实任务分组。built 标识是否已实现页面。 */
const SUBSYSTEMS: Subsystem[] = [
  {
    key: 'enterprise_access', label: '企业与权限', icon: <ApartmentOutlined />, built: true,
    menu: [
      { path: '/org/structure', label: '组织架构', icon: <ApartmentOutlined /> },
      { path: '/enterprise-apps', label: '企业模块', icon: <AppstoreOutlined /> },
      { path: '/enterprise-apps/permissions', label: '角色权限', icon: <SafetyOutlined /> },
      { path: '/org/users', label: '员工授权', icon: <UserOutlined /> },
    ],
    routes: [
      { path: '/org/structure', element: <Organizations /> },
      { path: '/org/users', element: <UsersPage /> },
      { path: '/enterprise-apps', element: <EnterpriseApplications section="applications" /> },
      { path: '/enterprise-apps/:appId', element: <EnterpriseApplicationDetail /> },
      { path: '/enterprise-apps/permissions', element: <EnterpriseAccessControl /> },
    ],
  },
  {
    key: 'enterprise_settings', label: '企业设置', icon: <SettingOutlined />, built: true,
    menu: [
      { path: '/org/admins', label: '管理员', icon: <TeamOutlined /> },
      { path: '/org/profile', label: '企业资料', icon: <ApartmentOutlined /> },
      { path: '/org/contact', label: '联系方式', icon: <PhoneOutlined /> },
      // 旧入口保留直达路由，但不再占用企业管理主导航。
      { path: '/org/roles', label: '角色设置', icon: <TeamOutlined />, hidden: true },
      { path: '/enterprise-apps/navigation', label: '员工导航', icon: <SettingOutlined />, hidden: true },
      { path: '/enterprise-apps/assistant', label: '业务助手', icon: <LinkOutlined />, hidden: true },
      { path: '/org/voices', label: '企业音色库', icon: <AudioOutlined />, hidden: true },
    ],
    routes: [
      { path: '/org/admins', element: <AdminManagement /> },
      { path: '/org/profile', element: <EnterpriseProfile /> },
      { path: '/org/contact', element: <ContactInfo /> },
      { path: '/org/roles', element: <RolesPage /> },
      { path: '/enterprise-apps/navigation', element: <EnterpriseApplications section="navigation" /> },
      { path: '/enterprise-apps/assistant', element: <EnterpriseApplications section="assistant" /> },
      { path: '/org/voices', element: <VoicesPage /> },
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
      { path: '/agent/rag', label: 'RAG知识库', icon: <DatabaseOutlined /> },
      { path: '/agent/memory', label: '长期记忆', icon: <ReadOutlined /> },
    ],
    routes: [
      { path: '/agent/workspaces', element: <Workspaces /> },
      { path: '/agent/agents', element: <Agents /> },
      { path: '/agent/rag', element: <Rag /> },
      { path: '/agent/memory', element: <MemoryPage /> },
    ],
  },
  {
    key: 'tools', label: '工具与技能', icon: <ToolOutlined />, built: true,
    menu: [
      { path: '/tools/skills', label: '技能', icon: <ToolOutlined /> },
    ],
    routes: [
      { path: '/tools/skills', element: <Skills /> },
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
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const mobileNavRef = useRef<HTMLElement>(null);
  const mobileNavTriggerRef = useRef<HTMLButtonElement>(null);
  const adminMainRef = useRef<HTMLElement>(null);
  const { isMobile } = useResponsiveLayout();
  const closeMobileNav = useMobileBackDismiss(mobileNavOpen, isMobile, setMobileNavOpen, 'admin-navigation');
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
    setMobileNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobile) setMobileNavOpen(false);
  }, [isMobile]);

  useEffect(() => {
    if (!isMobile || !mobileNavOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const focusable = () => Array.from(mobileNavRef.current?.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    ) ?? []).filter((item) => !item.hasAttribute('disabled'));
    const focusFrame = window.requestAnimationFrame(() => mobileNavRef.current?.focus());
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMobileNav();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
      if (mobileNavRef.current?.contains(document.activeElement)) {
        window.requestAnimationFrame(() => mobileNavTriggerRef.current?.focus());
      }
    };
  }, [closeMobileNav, isMobile, mobileNavOpen]);

  useEffect(() => {
    const main = adminMainRef.current;
    if (!main) return undefined;
    if (isMobile && mobileNavOpen) {
      main.setAttribute('inert', '');
      main.setAttribute('aria-hidden', 'true');
    } else {
      main.removeAttribute('inert');
      main.removeAttribute('aria-hidden');
    }
    return () => {
      main.removeAttribute('inert');
      main.removeAttribute('aria-hidden');
    };
  }, [isMobile, mobileNavOpen]);

  const ROLE_LABELS: Record<string, string> = {
    platform_super_admin: '超级平台管理员',
    enterprise_admin: '企业管理员',
    // 仅用于数据库迁移期间显示旧会话；新表单不再产生这些值。
    super_admin: '超级平台管理员',
    org_admin: '企业管理员',
  };

  // 扁平渲染全部已建成子系统的路由——单侧栏全路由可见，直达链接不再被重定向回首页
  // （原 activeSubsystem 状态不随 URL 同步的坑由此彻底移除）
  const allRoutes = SUBSYSTEMS.filter((s) => s.built)
    .flatMap((s) => s.routes ?? [])
    .filter((route) => !route.superOnly || isSuperAdmin());

  const navItemStyle = (active: boolean): CSSProperties => ({
    display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', borderRadius: 6,
    width: 'calc(100% - 12px)', border: 0, textAlign: 'left', fontFamily: 'inherit',
    cursor: 'pointer', fontSize: FS.body, lineHeight: 1, userSelect: 'none', margin: '1px 6px',
    background: active ? `${WB.primary}1A` : 'transparent',
    color: active ? WB.primary : '#4b5563', fontWeight: active ? 600 : 400,
  });

  const userInitial = (admin?.display_name || admin?.username || '?').slice(0, 1).toUpperCase();

  return (
    <ConfigProvider theme={antdTheme}>
      <div className="admin-shell" style={{ fontFamily: WB_FONT, background: '#f5f5f5' }}>
        <Button
          ref={mobileNavTriggerRef}
          className="admin-shell__mobile-trigger"
          aria-label={mobileNavOpen ? '关闭管理导航' : '打开管理导航'}
          aria-expanded={mobileNavOpen}
          icon={mobileNavOpen ? <CloseOutlined /> : <MenuOutlined />}
          onClick={() => {
            const willOpen = !mobileNavOpen;
            setMobileNavOpen(willOpen);
            if (willOpen) window.setTimeout(() => mobileNavRef.current?.focus(), 0);
          }}
        />
        {mobileNavOpen && <button className="responsive-shell__scrim" aria-label="关闭管理导航" onClick={closeMobileNav} />}
        {/* 左侧栏：终端式单栏（品牌 / 分组导航 / 底部用户） */}
        <aside
          ref={mobileNavRef}
          className={`admin-shell__sidebar${mobileNavOpen ? ' admin-shell__sidebar--open' : ''}`}
          role={isMobile ? 'dialog' : undefined}
          aria-modal={isMobile ? true : undefined}
          aria-label="管理导航"
          aria-hidden={isMobile && !mobileNavOpen}
          tabIndex={isMobile ? -1 : undefined}
          onTransitionEnd={() => {
            if (isMobile && mobileNavOpen) mobileNavRef.current?.focus();
          }}
          style={{ width: 220, background: WB.sidebar, borderRight: `1px solid ${WB.border}`, display: 'flex', flexDirection: 'column', flex: '0 0 auto' }}
        >
          {isMobile && mobileNavOpen && (
            <button
              type="button"
              className="admin-shell__sidebar-close"
              aria-label="关闭管理导航"
              autoFocus
              onClick={closeMobileNav}
            >
              <CloseOutlined />
            </button>
          )}
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
                  <button
                    type="button"
                    aria-expanded={expanded}
                    onClick={() => setExpandedGroups((current) => {
                      const next = new Set(current);
                      if (next.has(s.key)) next.delete(s.key); else next.add(s.key);
                      return next;
                    })}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', border: 0, background: 'transparent', textAlign: 'left', cursor: 'pointer', fontSize: FS.micro, fontWeight: 600, color: WB.textAux, letterSpacing: 0.4, textTransform: 'uppercase', padding: '8px 14px 4px 18px', userSelect: 'none' }}
                  >
                    <span style={{ display: 'inline-flex', fontSize: 10 }}>{expanded ? <DownOutlined /> : <RightOutlined />}</span>
                    <span>{s.label}</span>
                  </button>
                  {expanded && items.map((m) => {
                    const active = location.pathname === m.path;
                    return (
                      <button
                        type="button"
                        key={m.path}
                        onClick={() => navigate(m.path)}
                        style={navItemStyle(active)}
                        onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = WB.hover; }}
                        onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
                      >
                        <span style={{ fontSize: 16, display: 'inline-flex', color: active ? WB.primary : WB.textAux }}>{m.icon}</span>
                        <span>{m.label}</span>
                      </button>
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

        <main ref={adminMainRef} className="admin-shell__main" style={{ flex: 1, display: 'flex', flexDirection: 'column', background: '#fff', minWidth: 0 }}>
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
          width={isMobile ? '100%' : 720}
          rootClassName="responsive-fullscreen-drawer"
          title={<span><QuestionCircleOutlined style={{ color: WB.primary, marginRight: 6 }} />帮助文档</span>}
          styles={{ header: { borderBottom: `1px solid ${WB.border}`, marginBottom: 0 }, body: { padding: '18px 20px', background: '#fafafa' } }}
        >
          <HelpBody />
        </Drawer>
      </div>
    </ConfigProvider>
  );
}

function AdminApp() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/:slug/login" element={<OrgLogin />} />
        <Route path="/*" element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        } />
      </Routes>
    </AuthProvider>
  );
}

export default function App() {
  return (
    <Routes>
        {/* 终端用户门户完全独立于管理员会话。 */}
        <Route path="/:slug/terminal/login" element={
          <UserAuthProvider><UserLoginPage /></UserAuthProvider>
        } />
        <Route path="/:slug/terminal" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/:slug/terminal/tasks/:taskId" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/terminal" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/terminal/tasks/:taskId" element={
          <UserAuthProvider><UserRequireAuth><Terminal /></UserRequireAuth></UserAuthProvider>
        } />
        <Route path="/f/:fileId" element={
          <UserAuthProvider><FileDeepLinkPage /></UserAuthProvider>
        } />
        <Route path="/*" element={<AdminApp />} />
    </Routes>
  );
}
