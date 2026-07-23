import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { Navigate, Outlet } from 'react-router-dom';
import { api, getToken, getRefreshToken, setTokens, clearTokens } from '../api/client';
import Spinner from '../components/Spinner';
import ForcePasswordChange from '../components/ForcePasswordChange';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken() && !getRefreshToken()) {
      setLoading(false);
      return;
    }
    api
      .get('/api/auth/me')
      .then(setUser)
      .catch(() => clearTokens())
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username, password) => {
    const data = await api.post('/api/auth/login', { username, password });
    setTokens(data);
    setUser(data.user);
    return data.user;
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      try {
        await api.post('/api/auth/logout', { refresh_token: refreshToken });
      } catch {
        /* revocation is best-effort — clear locally regardless */
      }
    }
    clearTokens();
    setUser(null);
  }, []);

  const updateUser = useCallback((u) => setUser(u), []);

  const mustChangePassword = !!user?.must_change_password;

  return (
    <AuthContext.Provider
      value={{ user, loading, login, logout, updateUser, mustChangePassword }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}

export function ProtectedRoute() {
  const { user, loading, mustChangePassword, updateUser } = useAuth();
  if (loading) {
    return (
      <div className="fullscreen-center">
        <Spinner />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (mustChangePassword) return <ForcePasswordChange onChanged={updateUser} />;
  return <Outlet />;
}
