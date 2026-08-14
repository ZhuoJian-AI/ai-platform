import { createContext, useContext, useState, type ReactNode } from 'react';

export interface AdminUser {
  id: number;
  username: string;
  display_name: string | null;
  role: 'super_admin' | 'admin' | 'org_admin';
  is_active: boolean;
  must_change_password?: boolean;
  /** 组织绑定：org_admin 必填，平台级账号为 null。驱动「受限门户」（只看自己组织）。 */
  organization_id?: string | null;
  organization_name?: string | null;
  /** 组织 slug：org_admin 登录后用于失效时回跳到 /{slug}/login。平台级账号为 null。 */
  organization_slug?: string | null;
}

interface AuthContextType {
  token: string | null;
  admin: AdminUser | null;
  login: (token: string, admin: AdminUser) => void;
  logout: () => void;
  isAdmin: () => boolean;
  isSuperAdmin: () => boolean;
  /** 是否为组织级账号（绑定到单个组织）——驱动受限门户。 */
  isOrgScoped: () => boolean;
  isOrgAdmin: () => boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

const TOKEN_KEY = 'ai_infra_token';
const ADMIN_KEY = 'ai_infra_admin';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [admin, setAdmin] = useState<AdminUser | null>(() => {
    const stored = localStorage.getItem(ADMIN_KEY);
    return stored ? JSON.parse(stored) : null;
  });

  const login = (newToken: string, adminData: AdminUser) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(ADMIN_KEY, JSON.stringify(adminData));
    setToken(newToken);
    setAdmin(adminData);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(ADMIN_KEY);
    setToken(null);
    setAdmin(null);
  };

  const isAdmin = () => admin?.role === 'admin' || admin?.role === 'super_admin';
  const isSuperAdmin = () => admin?.role === 'super_admin';
  // 组织级账号：绑定了 organization_id（org_admin 或任何带组织绑定的账号）
  const isOrgScoped = () => !!admin?.organization_id;
  const isOrgAdmin = () => admin?.role === 'org_admin';

  return (
    <AuthContext.Provider value={{ token, admin, login, logout, isAdmin, isSuperAdmin, isOrgScoped, isOrgAdmin }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

/** 路由守卫组件 */
export function RequireAuth({ children }: { children: ReactNode }) {
  const { token, admin } = useAuth();
  if (!token) {
    // 组织级账号失效时回跳到 /{slug}/login，平台级账号回跳 /login
    const slug = admin?.organization_slug;
    window.location.href = slug ? `/${slug}/login` : '/login';
    return null;
  }
  return <>{children}</>;
}
