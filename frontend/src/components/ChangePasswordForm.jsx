import { useState } from 'react';
import { api } from '../api/client';

/**
 * Shared change-password form. Posts /api/auth/change-password and hands the
 * updated user to onSuccess. Used blocking (forced change) and in Profile.
 */
export default function ChangePasswordForm({ onSuccess, autoFocus = false }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const onSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (next !== confirm) {
      setError('New passwords do not match');
      return;
    }
    setBusy(true);
    try {
      const updated = await api.post('/api/auth/change-password', {
        current_password: current,
        new_password: next,
      });
      setCurrent('');
      setNext('');
      setConfirm('');
      onSuccess?.(updated);
    } catch (err) {
      setError(err.message || 'Could not change password');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="login-form">
      <div className="form-field">
        <label htmlFor="current-password">Current password</label>
        <input
          id="current-password"
          type="password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          autoComplete="current-password"
          autoFocus={autoFocus}
          required
        />
      </div>
      <div className="form-field">
        <label htmlFor="new-password">New password</label>
        <input
          id="new-password"
          type="password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          autoComplete="new-password"
          minLength={8}
          required
        />
        <span className="muted-text">At least 8 characters, different from your current password.</span>
      </div>
      <div className="form-field">
        <label htmlFor="confirm-password">Confirm new password</label>
        <input
          id="confirm-password"
          type="password"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          autoComplete="new-password"
          minLength={8}
          required
        />
      </div>
      {error && <div className="error-text">{error}</div>}
      <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
        {busy ? 'Saving…' : 'Change Password'}
      </button>
    </form>
  );
}
