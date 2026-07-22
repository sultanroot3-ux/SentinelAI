import { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import Badge from '../components/Badge';
import ChangePasswordForm from '../components/ChangePasswordForm';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { getTheme, setTheme } from '../theme';
import { fmtDate, titleCase } from '../utils/format';

export default function Profile() {
  const { user, updateUser } = useAuth();
  const toast = useToast();
  const [theme, setThemeState] = useState(getTheme());

  const onPasswordChanged = (updated) => {
    updateUser(updated);
    toast('Password changed', 'success');
  };

  const chooseTheme = (t) => {
    setTheme(t);
    setThemeState(t);
  };

  if (!user) return null;

  return (
    <div className="page">
      <div className="card pad profile-card">
        <div className="profile-head">
          <span className="avatar avatar-lg">
            {user.photo_url ? <img src={user.photo_url} alt="" /> : (user.name || '?').charAt(0)}
          </span>
          <div>
            <h2>{user.name}</h2>
            <div className="row-gap">
              <Badge value={user.role} />
              <Badge value={user.face_registered ? 'yes' : 'no'}>
                {user.face_registered ? 'Face registered' : 'Face not registered'}
              </Badge>
            </div>
          </div>
        </div>

        <dl className="profile-details">
          <div>
            <dt>Username</dt>
            <dd>{user.username}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd>{user.email || '—'}</dd>
          </div>
          <div>
            <dt>Department</dt>
            <dd>{user.department_name || '—'}</dd>
          </div>
          <div>
            <dt>Employee ID</dt>
            <dd>{user.employee_id || '—'}</dd>
          </div>
          <div>
            <dt>Access Level</dt>
            <dd>{user.access_level ?? '—'}</dd>
          </div>
          <div>
            <dt>Member Since</dt>
            <dd>{fmtDate(user.created_at)}</dd>
          </div>
        </dl>
      </div>

      <div className="card pad">
        <h2>Change Password</h2>
        <p className="muted-text">Choose a new password for your account.</p>
        <div className="spaced-top">
          <ChangePasswordForm onSuccess={onPasswordChanged} />
        </div>
      </div>

      <div className="card pad">
        <h2>Appearance</h2>
        <p className="muted-text">Theme preference is saved on this device.</p>
        <div className="theme-picker">
          {['dark', 'light'].map((t) => (
            <button
              key={t}
              className={`theme-option ${theme === t ? 'active' : ''}`}
              onClick={() => chooseTheme(t)}
            >
              <Icon name={t === 'dark' ? 'moon' : 'sun'} size={18} />
              {titleCase(t)} mode
              {theme === t && <Icon name="check" size={15} className="accent-text" />}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
