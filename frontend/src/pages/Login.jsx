import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate('/', { replace: true });
    } catch (err) {
      if (err.status === 429) {
        const fallback = err.retryAfter
          ? `Too many login attempts — try again in ${err.retryAfter} seconds.`
          : 'Too many login attempts — please try again later.';
        setError(err.message && !err.message.startsWith('Request failed') ? err.message : fallback);
      } else {
        setError(err.message || 'Login failed');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-screen">
      <div className="login-card card">
        <div className="login-logo">
          <span className="sidebar-logo-shield">🛡</span>
          <h1>
            Sentinel<span className="accent-text">AI</span>
          </h1>
          <p className="login-tagline">Intelligent Vision Security Platform</p>
        </div>
        <form onSubmit={onSubmit} className="login-form">
          <div className="form-field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              autoFocus
              required
            />
          </div>
          <div className="form-field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
          {error && <div className="error-text">{error}</div>}
          <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign In'}
          </button>
          <p className="login-hint">default: admin / admin123</p>
        </form>
      </div>
    </div>
  );
}
