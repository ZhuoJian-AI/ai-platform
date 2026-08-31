import { createContext, useContext, useState, type ReactNode } from 'react';

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
  logout: () => void;
}

const UserAuthContext = createContext<UserAuthContextType | null>(null);

const TOKEN_KEY = 'ai_infra_user_token';
const USER_KEY = 'ai_infra_user';

export function UserAuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<TerminalUserState | null>(() => {
    const stored = localStorage.getItem(USER_KEY);
    return stored ? JSON.parse(stored) : null;
  });

  const login = (newToken: string, userState: TerminalUserState) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    localStorage.setItem(USER_KEY, JSON.stringify(userState));
    setToken(newToken);
    setUser(userState);
  };

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY);
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
    window.location.href = slug ? `/${slug}/terminal/login` : '/login';
    return null;
  }
  return <>{children}</>;
}
