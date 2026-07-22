import { useEffect, useState } from 'react';
import { api } from '../api/client';
import Spinner from '../components/Spinner';
import { useToast } from '../components/Toast';

const DEFAULTS = {
  recognition_threshold: 0.45,
  liveness_enabled: false,
  camera_source: '0',
  notify_on_unknown: true,
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

        <div className="modal-footer settings-footer">
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  );
}
