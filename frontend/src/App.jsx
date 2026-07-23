import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, ProtectedRoute } from './context/AuthContext';
import { ToastProvider } from './components/Toast';
import Layout from './components/Layout';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import LiveCamera from './pages/LiveCamera';
import Investigation from './pages/Investigation';
import Cameras from './pages/Cameras';
import CameraLocations from './pages/CameraLocations';
import Visitors from './pages/Visitors';
import Watchlists from './pages/Watchlists';
import Rbac from './pages/Rbac';
import AuditLogs from './pages/AuditLogs';
import AccessHistory from './pages/AccessHistory';
import VisitorLogs from './pages/VisitorLogs';
import UnknownVisitors from './pages/UnknownVisitors';
import Cases from './pages/Cases';
import Users from './pages/Users';
import Departments from './pages/Departments';
import Reports from './pages/Reports';
import Analytics from './pages/Analytics';
import Notifications from './pages/Notifications';
import Settings from './pages/Settings';
import Profile from './pages/Profile';

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route element={<ProtectedRoute />}>
              <Route element={<Layout />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/live" element={<LiveCamera />} />
                <Route path="/investigation" element={<Investigation />} />
                <Route path="/cameras" element={<Cameras />} />
                <Route path="/camera-locations" element={<CameraLocations />} />
                <Route path="/visitors" element={<Visitors />} />
                <Route path="/watchlists" element={<Watchlists />} />
                <Route path="/rbac" element={<Rbac />} />
                <Route path="/audit" element={<AuditLogs />} />
                <Route path="/access-history" element={<AccessHistory />} />
                <Route path="/logs" element={<VisitorLogs />} />
                <Route path="/unknown" element={<UnknownVisitors />} />
                <Route path="/cases" element={<Cases />} />
                <Route path="/users" element={<Users />} />
                <Route path="/departments" element={<Departments />} />
                <Route path="/reports" element={<Reports />} />
                <Route path="/analytics" element={<Analytics />} />
                <Route path="/notifications" element={<Notifications />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="/profile" element={<Profile />} />
              </Route>
            </Route>
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
