import ChangePasswordForm from './ChangePasswordForm';

/** Full-screen blocking card shown when the logged-in user must change their password. */
export default function ForcePasswordChange({ onChanged }) {
  return (
    <div className="login-screen">
      <div className="login-card card">
        <div className="login-logo">
          <span className="sidebar-logo-shield">🛡</span>
          <h1>
            Sentinel<span className="accent-text">AI</span>
          </h1>
          <p className="login-tagline">You must set a new password before continuing</p>
        </div>
        <ChangePasswordForm autoFocus onSuccess={onChanged} />
      </div>
    </div>
  );
}
