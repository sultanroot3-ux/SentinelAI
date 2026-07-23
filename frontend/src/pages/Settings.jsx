import { useEffect, useState } from 'react';
import { api } from '../api/client';
import Spinner from '../components/Spinner';
import { useToast } from '../components/Toast';

const DEFAULTS = {
  recognition_threshold: 0.45,
  liveness_enabled: false,
  camera_source: '0',
  notify_on_unknown: true,
  unknown_retention_days: 0,
  email_enabled: false,
  smtp_host: '',
  smtp_port: 587,
  smtp_user: '',
  smtp_password: '',
  smtp_from: '',
  smtp_to: '',
  smtp_tls: true,
  telegram_enabled: false,
  telegram_bot_token: '',
  telegram_chat_id: '',
  discord_enabled: false,
  discord_webhook_url: '',
};

function toBool(v) {
  if (typeof v === 'boolean') return v;
  return String(v).toLowerCase() === 'true' || v === 1 || v === '1';
}

export default function Settings() {
  const toast = useToast();
  const [form, setForm] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .get('/api/settings')
      .then((d) => {
        if (!alive) return;
        setForm({
          recognition_threshold: Number(d?.recognition_threshold ?? DEFAULTS.recognition_threshold),
          liveness_enabled: toBool(d?.liveness_enabled ?? DEFAULTS.liveness_enabled),
          camera_source: String(d?.camera_source ?? DEFAULTS.camera_source),
          notify_on_unknown: toBool(d?.notify_on_unknown ?? DEFAULTS.notify_on_unknown),
          unknown_retention_days: Number(d?.unknown_retention_days ?? DEFAULTS.unknown_retention_days),
          email_enabled: toBool(d?.email_enabled ?? DEFAULTS.email_enabled),
          smtp_host: String(d?.smtp_host ?? DEFAULTS.smtp_host),
          smtp_port: Number(d?.smtp_port ?? DEFAULTS.smtp_port),
          smtp_user: String(d?.smtp_user ?? DEFAULTS.smtp_user),
          smtp_password: String(d?.smtp_password ?? DEFAULTS.smtp_password),
          smtp_from: String(d?.smtp_from ?? DEFAULTS.smtp_from),
          smtp_to: String(d?.smtp_to ?? DEFAULTS.smtp_to),
          smtp_tls: toBool(d?.smtp_tls ?? DEFAULTS.smtp_tls),
          telegram_enabled: toBool(d?.telegram_enabled ?? DEFAULTS.telegram_enabled),
          telegram_bot_token: String(d?.telegram_bot_token ?? DEFAULTS.telegram_bot_token),
          telegram_chat_id: String(d?.telegram_chat_id ?? DEFAULTS.telegram_chat_id),
          discord_enabled: toBool(d?.discord_enabled ?? DEFAULTS.discord_enabled),
          discord_webhook_url: String(d?.discord_webhook_url ?? DEFAULTS.discord_webhook_url),
        });
      })
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, []);

  const save = async () => {
    setSaving(true);
    try {
      await api.put('/api/settings', {
        recognition_threshold: Number(form.recognition_threshold),
        liveness_enabled: form.liveness_enabled,
        camera_source: form.camera_source,
        notify_on_unknown: form.notify_on_unknown,
        unknown_retention_days: Number(form.unknown_retention_days),
        email_enabled: form.email_enabled,
        smtp_host: form.smtp_host,
        smtp_port: Number(form.smtp_port),
        smtp_user: form.smtp_user,
        smtp_password: form.smtp_password,
        smtp_from: form.smtp_from,
        smtp_to: form.smtp_to,
        smtp_tls: form.smtp_tls,
        telegram_enabled: form.telegram_enabled,
        telegram_bot_token: form.telegram_bot_token,
        telegram_chat_id: form.telegram_chat_id,
        discord_enabled: form.discord_enabled,
        discord_webhook_url: form.discord_webhook_url,
      });
      toast('Settings saved', 'success');
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  if (error && !form) return <div className="error-text card pad">{error}</div>;
  if (!form) {
    return (
      <div className="fullpage-loading">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="card pad settings-card">
        <h2>Recognition</h2>
        <div className="form-field">
          <label>
            Recognition threshold —{' '}
            <strong className="accent-text">{Number(form.recognition_threshold).toFixed(2)}</strong>
          </label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={form.recognition_threshold}
            onChange={(e) =>
              setForm((f) => ({ ...f, recognition_threshold: Number(e.target.value) }))
            }
          />
          <span className="muted-text">
            Lower = more matches (more false positives). Higher = stricter matching. Default 0.45.
          </span>
        </div>

        <label className="toggle-row">
          <input
            type="checkbox"
            checked={form.liveness_enabled}
            onChange={(e) => setForm((f) => ({ ...f, liveness_enabled: e.target.checked }))}
          />
          <span className="toggle-track" />
          <span>
            <strong>Liveness detection</strong>
            <span className="muted-text block">
              Reject photos and screens presented to the camera.
            </span>
          </span>
        </label>

        <h2 className="section-gap">Camera</h2>
        <div className="form-field">
          <label>Camera source</label>
          <input
            value={form.camera_source}
            onChange={(e) => setForm((f) => ({ ...f, camera_source: e.target.value }))}
            placeholder='Device index (e.g. "0") or stream URL'
          />
          <span className="muted-text">
            A local device index like <code>0</code>, or an RTSP/HTTP stream URL.
          </span>
        </div>

        <h2 className="section-gap">Data Retention</h2>
        <div className="form-field">
          <label>Unknown-visitor retention (days)</label>
          <input
            type="number"
            min="0"
            max="3650"
            value={form.unknown_retention_days}
            onChange={(e) =>
              setForm((f) => ({ ...f, unknown_retention_days: e.target.value }))
            }
          />
          <span className="muted-text">
            Automatically delete unknown-visitor records (snapshot, face
            embedding and database entry) older than this many days.{' '}
            <code>0</code> disables purging. Records linked to a case or on a
            watchlist are never purged. Every purge is written to the audit
            log.
          </span>
        </div>

        <h2 className="section-gap">Notifications</h2>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={form.notify_on_unknown}
            onChange={(e) => setForm((f) => ({ ...f, notify_on_unknown: e.target.checked }))}
          />
          <span className="toggle-track" />
          <span>
            <strong>Notify on unknown visitor</strong>
            <span className="muted-text block">
              Create an alert whenever an unrecognized face is detected.
            </span>
          </span>
        </label>

        <h2 className="section-gap">Notification Channels</h2>

        <div className="channel-card">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={form.email_enabled}
              onChange={(e) => setForm((f) => ({ ...f, email_enabled: e.target.checked }))}
            />
            <span className="toggle-track" />
            <span>
              <strong>Email (SMTP)</strong>
              <span className="muted-text block">Send alerts by email through an SMTP server.</span>
            </span>
          </label>
          <div className="form-grid two-col">
            <div className="form-field">
              <label>SMTP host</label>
              <input
                value={form.smtp_host}
                onChange={(e) => setForm((f) => ({ ...f, smtp_host: e.target.value }))}
                placeholder="smtp.gmail.com"
              />
            </div>
            <div className="form-field">
              <label>SMTP port</label>
              <input
                type="number"
                value={form.smtp_port}
                onChange={(e) => setForm((f) => ({ ...f, smtp_port: e.target.value }))}
                placeholder="587"
              />
            </div>
            <div className="form-field">
              <label>Username</label>
              <input
                value={form.smtp_user}
                onChange={(e) => setForm((f) => ({ ...f, smtp_user: e.target.value }))}
                placeholder="user@example.com"
              />
            </div>
            <div className="form-field">
              <label>Password</label>
              <input
                type="password"
                value={form.smtp_password}
                onChange={(e) => setForm((f) => ({ ...f, smtp_password: e.target.value }))}
                autoComplete="new-password"
              />
            </div>
            <div className="form-field">
              <label>From address</label>
              <input
                value={form.smtp_from}
                onChange={(e) => setForm((f) => ({ ...f, smtp_from: e.target.value }))}
                placeholder="alerts@example.com"
              />
            </div>
            <div className="form-field">
              <label>To addresses</label>
              <input
                value={form.smtp_to}
                onChange={(e) => setForm((f) => ({ ...f, smtp_to: e.target.value }))}
                placeholder="a@example.com, b@example.com"
              />
            </div>
          </div>
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={form.smtp_tls}
              onChange={(e) => setForm((f) => ({ ...f, smtp_tls: e.target.checked }))}
            />
            <span className="toggle-track" />
            <span>
              <strong>Use TLS</strong>
              <span className="muted-text block">Encrypt the SMTP connection (recommended).</span>
            </span>
          </label>
          <span className="muted-text block">
            e.g. <code>smtp.gmail.com</code> + app password
          </span>
        </div>

        <div className="channel-card">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={form.telegram_enabled}
              onChange={(e) => setForm((f) => ({ ...f, telegram_enabled: e.target.checked }))}
            />
            <span className="toggle-track" />
            <span>
              <strong>Telegram</strong>
              <span className="muted-text block">Send alerts to a Telegram chat via a bot.</span>
            </span>
          </label>
          <div className="form-grid two-col">
            <div className="form-field">
              <label>Bot token</label>
              <input
                type="password"
                value={form.telegram_bot_token}
                onChange={(e) => setForm((f) => ({ ...f, telegram_bot_token: e.target.value }))}
                autoComplete="new-password"
              />
            </div>
            <div className="form-field">
              <label>Chat ID</label>
              <input
                value={form.telegram_chat_id}
                onChange={(e) => setForm((f) => ({ ...f, telegram_chat_id: e.target.value }))}
                placeholder="123456789"
              />
            </div>
          </div>
          <span className="muted-text block spaced-top">
            Create a bot with <code>@BotFather</code>, get chat id from <code>@userinfobot</code>
          </span>
        </div>

        <div className="channel-card">
          <label className="toggle-row">
            <input
              type="checkbox"
              checked={form.discord_enabled}
              onChange={(e) => setForm((f) => ({ ...f, discord_enabled: e.target.checked }))}
            />
            <span className="toggle-track" />
            <span>
              <strong>Discord</strong>
              <span className="muted-text block">Send alerts to a Discord channel webhook.</span>
            </span>
          </label>
          <div className="form-field">
            <label>Webhook URL</label>
            <input
              type="password"
              value={form.discord_webhook_url}
              onChange={(e) => setForm((f) => ({ ...f, discord_webhook_url: e.target.value }))}
              autoComplete="new-password"
            />
          </div>
          <span className="muted-text block spaced-top">
            Server Settings → Integrations → Webhooks
          </span>
        </div>

        <div className="modal-footer settings-footer">
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
