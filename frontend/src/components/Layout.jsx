import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { api, asPage } from '../api/client';
import { getTheme, setTheme } from '../theme';
import { titleCase } from '../utils/format';
import Icon from './Icons';

// `roles`: only these roles see the item (backend enforces regardless).
const NAV = [
  { to: '/', label: 'Dashboard', icon: 'dashboard' },
  { to: '/live', label: 'Live Camera', icon: 'camera' },
  { to: '/investigation', label: 'Investigation', icon: 'eye', roles: ['admin', 'security_officer'] },
  { to: '/logs', label: 'Visitor Logs', icon: 'logs' },
  { to: '/unknown', label: 'Unknown Visitors', icon: 'unknown' },
  { to: '/cases', label: 'Cases', icon: 'cases' },
  { to: '/visitors', label: 'Visitors', icon: 'logs', roles: ['admin', 'security_officer', 'receptionist'] },
  { to: '/access-history', label: 'Access History', icon: 'shield', roles: ['admin', 'security_officer', 'receptionist'] },
  { to: '/watchlists', label: 'Watchlists', icon: 'alert', roles: ['admin', 'security_officer'] },
  { to: '/cameras', label: 'Cameras', icon: 'camera', roles: ['admin', 'it', 'security_officer'] },
  { to: '/camera-locations', label: 'Camera Locations', icon: 'departments', roles: ['admin', 'it', 'security_officer'] },
  { to: '/users', label: 'Users', icon: 'users' },
  { to: '/departments', label: 'Departments', icon: 'departments' },
  { to: '/rbac', label: 'Roles & Permissions', icon: 'shield', roles: ['admin', 'security_officer', 'it'] },
  { to: '/audit', label: 'Audit Log', icon: 'cases', roles: ['admin', 'security_officer'] },
  { to: '/reports', label: 'Reports', icon: 'reports' },
  { to: '/analytics', label: 'Analytics', icon: 'analytics' },
  { to: '/notifications', label: 'Notifications', icon: 'bell' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
  { to: '/profile', label: 'Profile', icon: 'profile' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [theme, setThemeState] = useState(getTheme());
  const [unread, setUnread] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(null);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    setThemeState(next);
  };

  // Poll unread notification count.
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .get('/api/notifications', { unread_only: true })
        .then((data) => alive && setUnread(asPage(data).items.length))
        .catch(() => {});
    load();
    const id = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [location.pathname]);

  // Close user menu on outside click.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [menuOpen]);

  const current = NAV.find(
    (n) => n.to === location.pathname || (n.to !== '/' && location.pathname.startsWith(n.to))
  );

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span className="sidebar-logo-shield">🛡</span>
          <span className="sidebar-logo-text">
            Sentinel<span className="accent-text">AI</span>
          </span>
        </div>
        <nav className="sidebar-nav">
          {NAV.filter((item) => !item.roles || item.roles.includes(user?.role)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            >
              <Icon name={item.icon} size={17} />
              <span>{item.label}</span>
              {item.to === '/notifications' && unread > 0 && (
                <span className="nav-count">{unread}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-footer">Intelligent Vision Security</div>
      </aside>

      <div className="main-area">
        <header className="topbar">
          <h1 className="topbar-title">{current ? current.label : 'SentinelAI'}</h1>
          <div className="topbar-actions">
            <button
              className="icon-btn"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
            </button>
            <button
              className="icon-btn bell-btn"
              onClick={() => navigate('/notifications')}
              title="Notifications"
            >
              <Icon name="bell" />
              {unread > 0 && <span className="bell-badge">{unread > 99 ? '99+' : unread}</span>}
            </button>
            <div className="user-menu" ref={menuRef}>
              <button className="user-menu-trigger" onClick={() => setMenuOpen((o) => !o)}>
                <span className="avatar">
                  {user?.photo_url ? (
                    <img src={user.photo_url} alt="" />
                  ) : (
                    (user?.name || '?').charAt(0).toUpperCase()
                  )}
                </span>
                <span className="user-menu-name">{user?.name}</span>
              </button>
              {menuOpen && (
                <div className="user-menu-dropdown">
                  <div className="user-menu-info">
                    <strong>{user?.name}</strong>
                    <span>{titleCase(user?.role)}</span>
                  </div>
                  <button
                    className="user-menu-item"
                    onClick={() => {
                      setMenuOpen(false);
                      navigate('/profile');
                    }}
                  >
                    <Icon name="profile" size={15} /> Profile
                  </button>
                  <button className="user-menu-item danger" onClick={handleLogout}>
                    <Icon name="logout" size={15} /> Logout
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
