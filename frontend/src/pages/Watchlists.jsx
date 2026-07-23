import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';
import { useToast } from '../components/Toast';
import { fmtDate } from '../utils/format';

const EMPTY_FORM = { name: '', description: '', level: 'warning' };
const EMPTY_ENTRY = { subject_type: 'employee', user_id: '', unknown_face_id: '', reason: '' };
const LEVEL_BADGE = { info: 'pending', warning: 'warning', alert: 'offline' };

export default function Watchlists() {
  const toast = useToast();
  const [lists, setLists] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const [entryTarget, setEntryTarget] = useState(null); // watchlist for new entry
  const [entryForm, setEntryForm] = useState(EMPTY_ENTRY);
  const [entryError, setEntryError] = useState('');

  const [deleteTarget, setDeleteTarget] = useState(null); // {type:'list'|'entry', ...}

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/watchlists')
      .then((rows) => setLists(rows || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get('/api/users')
      .then((rows) => setUsers(Array.isArray(rows) ? rows : []))
      .catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    if (!search) return lists || [];
    const s = search.toLowerCase();
    return (lists || []).filter(
      (wl) =>
        wl.name.toLowerCase().includes(s) ||
        (wl.description || '').toLowerCase().includes(s) ||
        wl.entries.some((e) =>
          [e.user_name, e.unknown_person_id, e.reason]
            .filter(Boolean)
            .some((v) => v.toLowerCase().includes(s))
        )
    );
  }, [lists, search]);

  const createList = async () => {
    setSaving(true);
    setFormError('');
    try {
      await api.post('/api/watchlists', {
        name: form.name.trim(),
        description: form.description.trim() || null,
        level: form.level,
      });
      toast('Watchlist created', 'success');
      setCreating(false);
      load();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const addEntry = async () => {
    setSaving(true);
    setEntryError('');
    try {
      const payload = { reason: entryForm.reason.trim() || null };
      if (entryForm.subject_type === 'employee') {
        if (!entryForm.user_id) throw new Error('Select an employee');
        payload.user_id = Number(entryForm.user_id);
      } else {
        if (!entryForm.unknown_face_id) throw new Error('Enter an unknown person record ID');
        payload.unknown_face_id = Number(entryForm.unknown_face_id);
      }
      await api.post(`/api/watchlists/${entryTarget.id}/entries`, payload);
      toast('Entry added', 'success');
      setEntryTarget(null);
      load();
    } catch (e) {
      setEntryError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const runDelete = async () => {
    try {
      if (deleteTarget.type === 'list') {
        await api.del(`/api/watchlists/${deleteTarget.list.id}`);
        toast('Watchlist deleted', 'success');
      } else {
        await api.del(
          `/api/watchlists/${deleteTarget.list.id}/entries/${deleteTarget.entry.id}`
        );
        toast('Entry removed', 'success');
      }
      setDeleteTarget(null);
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row space-between">
          <div className="form-field inline">
            <label>Search</label>
            <input
              type="search"
              placeholder="List, person, reason…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button
            className="btn btn-primary"
            onClick={() => {
              setForm(EMPTY_FORM);
              setFormError('');
              setCreating(true);
            }}
          >
            <Icon name="plus" size={15} /> New Watchlist
          </button>
        </div>

        {loading && <Spinner />}
        {error && <div className="error-text">{error}</div>}
        {!loading && !error && filtered.length === 0 && (
          <EmptyState
            icon="alert"
            title="No watchlists"
            message="Create a watchlist to flag employees or unknown persons in investigations."
          />
        )}

        {filtered.map((wl) => (
          <div className="card pad watchlist-card" key={wl.id}>
            <div className="card-title-row">
              <h3>
                {wl.name}{' '}
                <Badge value={LEVEL_BADGE[wl.level] || wl.level}>{wl.level}</Badge>{' '}
                {!wl.active && <Badge value="offline">inactive</Badge>}
              </h3>
              <div className="row-gap">
                <span className="muted-text">Created {fmtDate(wl.created_at)}</span>
                <button
                  className="btn btn-secondary"
                  onClick={() => {
                    setEntryForm(EMPTY_ENTRY);
                    setEntryError('');
                    setEntryTarget(wl);
                  }}
                >
                  <Icon name="plus" size={14} /> Add Entry
                </button>
                <button
                  className="icon-btn danger"
                  title="Delete watchlist"
                  onClick={() => setDeleteTarget({ type: 'list', list: wl })}
                >
                  <Icon name="trash" size={15} />
                </button>
              </div>
            </div>
            {wl.description && <p className="muted-text">{wl.description}</p>}
            {wl.entries.length === 0 ? (
              <p className="muted-text">No entries.</p>
            ) : (
              <ul className="report-list">
                {wl.entries.map((e) => (
                  <li key={e.id} className="watchlist-entry">
                    <span>
                      {e.user_name ? (
                        <>
                          <Icon name="users" size={13} /> {e.user_name}
                        </>
                      ) : (
                        <>
                          <Icon name="unknown" size={13} /> {e.unknown_person_id || `record #${e.unknown_face_id}`}
                        </>
                      )}{' '}
                      — {e.reason || 'no reason recorded'}
                      <span className="muted-text"> · added {fmtDate(e.created_at)}</span>
                    </span>
                    <button
                      className="icon-btn danger"
                      title="Remove entry"
                      onClick={() => setDeleteTarget({ type: 'entry', list: wl, entry: e })}
                    >
                      <Icon name="x" size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      <Modal
        open={creating}
        title="New Watchlist"
        onClose={() => setCreating(false)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={createList}
              disabled={saving || !form.name.trim()}
            >
              {saving ? 'Saving…' : 'Create'}
            </button>
          </>
        }
      >
        <div className="form-field">
          <label>Name</label>
          <input
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
        </div>
        <div className="form-field">
          <label>Description</label>
          <input
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
        </div>
        <div className="form-field">
          <label>Alert level</label>
          <select
            value={form.level}
            onChange={(e) => setForm((f) => ({ ...f, level: e.target.value }))}
          >
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="alert">Alert</option>
          </select>
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>

      <Modal
        open={!!entryTarget}
        title={`Add entry to "${entryTarget?.name || ''}"`}
        onClose={() => setEntryTarget(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setEntryTarget(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={addEntry} disabled={saving}>
              {saving ? 'Saving…' : 'Add Entry'}
            </button>
          </>
        }
      >
        <div className="form-field">
          <label>Subject</label>
          <select
            value={entryForm.subject_type}
            onChange={(e) => setEntryForm((f) => ({ ...f, subject_type: e.target.value }))}
          >
            <option value="employee">Employee</option>
            <option value="unknown">Unknown person</option>
          </select>
        </div>
        {entryForm.subject_type === 'employee' ? (
          <div className="form-field">
            <label>Employee</label>
            <select
              value={entryForm.user_id}
              onChange={(e) => setEntryForm((f) => ({ ...f, user_id: e.target.value }))}
            >
              <option value="">Select…</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.username})
                </option>
              ))}
            </select>
          </div>
        ) : (
          <div className="form-field">
            <label>Unknown person record ID (from Unknown Visitors)</label>
            <input
              type="number"
              min="1"
              value={entryForm.unknown_face_id}
              onChange={(e) =>
                setEntryForm((f) => ({ ...f, unknown_face_id: e.target.value }))
              }
            />
          </div>
        )}
        <div className="form-field">
          <label>Reason</label>
          <input
            value={entryForm.reason}
            onChange={(e) => setEntryForm((f) => ({ ...f, reason: e.target.value }))}
          />
        </div>
        {entryError && <div className="error-text spaced-top">{entryError}</div>}
      </Modal>

      <Modal
        open={!!deleteTarget}
        title={deleteTarget?.type === 'list' ? 'Delete watchlist?' : 'Remove entry?'}
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setDeleteTarget(null)}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={runDelete}>
              {deleteTarget?.type === 'list' ? 'Delete' : 'Remove'}
            </button>
          </>
        }
      >
        {deleteTarget?.type === 'list' ? (
          <p>
            Watchlist <strong>{deleteTarget?.list?.name}</strong> and all its entries will be
            permanently removed.
          </p>
        ) : (
          <p>
            <strong>
              {deleteTarget?.entry?.user_name ||
                deleteTarget?.entry?.unknown_person_id ||
                'This entry'}
            </strong>{' '}
            will be removed from <strong>{deleteTarget?.list?.name}</strong>.
          </p>
        )}
      </Modal>
    </div>
  );
}
