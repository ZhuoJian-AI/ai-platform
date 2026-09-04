import { createContext, useContext, useState, type ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

export interface TerminalUserState {
  id: string;
  username: string;
  display_name: string | null;
  role: string;
  organization_id: string;
  organization_slug: string | null;
  organization_name: string | null;
  department_ids: string[];
  department_id: string | null;
  team_id: string | null;
}

interface UserAuthContextType {
  token: string | null;
  user: TerminalUserState | null;
  login: (token: string, user: TerminalUserState) => void;
  logout: () => Promise<void>;
}

const UserAuthContext = createContext<UserAuthContextType | null>(null);

const TOKEN_KEY = 'ai_infra_user_token';
const USER_KEY = 'ai_infra_user';

export function UserAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => sessionStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<TerminalUserState | null>(() => {
    const stored = localStorage.getItem(USER_KEY);
    return stored ? JSON.parse(stored) : null;
  });

  const login = (newToken: string, userState: TerminalUserState) => {
    sessionStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(userState));
    setToken(newToken);
    setUser(userState);
  };

  const logout = async () => {
    const currentToken = sessionStorage.getItem(TOKEN_KEY);
    if (currentToken) {
      try {
        const response = await fetch('/api/v1/users/logout', {
          method: 'POST',
          credentials: 'include',
          keepalive: true,
          headers: { Authorization: `Bearer ${currentToken}` },
        });
        if (!response.ok && response.status !== 401) throw new Error('logout failed');
      } catch {
        window.alert('退出失败，当前会话尚未撤销，请检查网络后重试。');
        return;
      }
    }
    sessionStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken(null);
    setUser(null);
  };

  return (
    <UserAuthContext.Provider value={{ token, user, login, logout }}>
      {children}
    </UserAuthContext.Provider>
  );
}

export function useUserAuth() {
  const ctx = useContext(UserAuthContext);
  if (!ctx) throw new Error('useUserAuth must be used within UserAuthProvider');
  return ctx;
}

/** 终端用户路由守卫：无 token 回跳到当前 slug 的用户登录页。 */
export function UserRequireAuth({ children }: { children: ReactNode }) {
  const { token } = useUserAuth();
  if (!token) {
    const m = window.location.pathname.match(/^\/([^/]+)\/terminal/);
    const slug = m ? m[1] : null;
    return <Navigate to={slug ? `/${slug}/terminal/login` : '/login'} replace />;
  }
  return <>{children}</>;
}
