import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react';
import { Spin } from 'antd';
import { Navigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import {
  adminFetch,
  clearAdminSession,
  getAdminOrganizationSlug,
  migrateLegacyAdminSession,
  onAdminSessionExpired,
  rotateAdminOrganizationScope,
  setAdminSession,
} from '../auth/adminSession';

const BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

export type AdminRole = 'platform_super_admin' | 'enterprise_admin';

export interface AdminUser {
  id: number;
  username: string;
  display_name: string | null;
  role: AdminRole;
  is_active: boolean;
  /** enterprise_admin 必填且登录后不可切换。 */
  organization_id?: string | null;
  organization_name?: string | null;
  organization_slug?: string | null;
}

type AuthStatus = 'loading' | 'authenticated' | 'anonymous';

interface AuthContextType {
  status: AuthStatus;
  admin: AdminUser | null;
  loginRedirectSlug: string | null;
  /** accessToken 只用于旧服务的当前页面内存兼容，从不写入浏览器存储。 */
  login: (accessToken: string | null, admin: AdminUser, csrfToken?: string | null) => void;
  logout: () => void;
  isAdmin: () => boolean;
  isSuperAdmin: () => boolean;
  isOrgScoped: () => boolean;
  isOrgAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

function legacyCompatibleRole(role: unknown): AdminRole | null {
  if (role === 'platform_super_admin' || role === 'enterprise_admin') return role;
  // Read-only compatibility during the database role migration. The legacy
  // middle-level `admin` is intentionally rejected because mapping it upward
  // would silently grant platform-super-admin authority.
  if (role === 'super_admin') return 'platform_super_admin';
  if (role === 'org_admin') return 'enterprise_admin';
  return null;
}

export function normalizeAdminUser(value: unknown): AdminUser | null {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const role = legacyCompatibleRole(raw.role);
  if (!role || typeof raw.id !== 'number' || typeof raw.username !== 'string' || raw.is_active !== true) return null;
  const organizationId = typeof raw.organization_id === 'string' ? raw.organization_id : null;
  if (role === 'enterprise_admin' && !organizationId) return null;
  if (role === 'platform_super_admin' && organizationId) return null;
  return {
    id: raw.id,
    username: raw.username,
    display_name: typeof raw.display_name === 'string' ? raw.display_name : null,
    role,
    is_active: true,
    organization_id: organizationId,
    organization_name: typeof raw.organization_name === 'string' ? raw.organization_name : null,
    organization_slug: typeof raw.organization_slug === 'string' ? raw.organization_slug : null,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [migratedSession] = useState(() => migrateLegacyAdminSession());
  const [status, setStatus] = useState<AuthStatus>('loading');
  const [admin, setAdmin] = useState<AdminUser | null>(null);
  const [loginRedirectSlug, setLoginRedirectSlug] = useState<string | null>(() => getAdminOrganizationSlug());

  const expireSession = useCallback(() => {
    rotateAdminOrganizationScope();
    queryClient.clear();
    clearAdminSession();
    setAdmin(null);
    setStatus('anonymous');
  }, [queryClient]);

  useEffect(() => {
    let disposed = false;
    if (migratedSession.organizationSlug) setLoginRedirectSlug(migratedSession.organizationSlug);
    const unsubscribe = onAdminSessionExpired(expireSession);
    adminFetch(`${BASE_URL}/api/v1/auth/me`, { cache: 'no-store' }, {
      notifyOnUnauthorized: false,
      organizationScoped: false,
    }).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const authenticatedAdmin = normalizeAdminUser(await response.json());
      if (!authenticatedAdmin) throw new Error('Invalid administrator session');
      if (disposed) return;
      setAdminSession(migratedSession.accessToken, authenticatedAdmin.organization_slug);
      setLoginRedirectSlug(authenticatedAdmin.organization_slug ?? null);
      setAdmin(authenticatedAdmin);
      setStatus('authenticated');
    }).catch(() => {
      if (!disposed) expireSession();
    });
    return () => { disposed = true; unsubscribe(); };
  }, [expireSession, migratedSession]);

  const login = useCallback((accessToken: string | null, adminData: AdminUser, csrfToken?: string | null) => {
    rotateAdminOrganizationScope();
    queryClient.clear();
    setAdminSession(accessToken, adminData.organization_slug, csrfToken);
    setLoginRedirectSlug(adminData.organization_slug ?? null);
    setAdmin(adminData);
    setStatus('authenticated');
  }, [queryClient]);

  const logout = useCallback(() => {
    // Start server-side revocation while the optional legacy in-memory bearer
    // still exists, then immediately remove all client-side authority.
    void adminFetch(`${BASE_URL}/api/v1/auth/logout`, { method: 'POST' }, {
      notifyOnUnauthorized: false,
      organizationScoped: false,
    }).catch(() => undefined);
    expireSession();
  }, [expireSession]);

  const isAdmin = () => status === 'authenticated';
  const isSuperAdmin = () => admin?.role === 'platform_super_admin';
  const isOrgScoped = () => admin?.role === 'enterprise_admin';
  const isOrgAdmin = () => admin?.role === 'enterprise_admin';

  return (
    <AuthContext.Provider value={{ status, admin, loginRedirectSlug, login, logout, isAdmin, isSuperAdmin, isOrgScoped, isOrgAdmin }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

/** Cookie-first route guard; waits for /auth/me before deciding. */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { status, loginRedirectSlug } = useAuth();
  if (status === 'loading') {
    return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}><Spin size="large" /></div>;
  }
  if (status !== 'authenticated') {
    return <Navigate to={loginRedirectSlug ? `/${loginRedirectSlug}/login` : '/login'} replace />;
  }
  return <>{children}</>;
}
