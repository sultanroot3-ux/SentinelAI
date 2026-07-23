import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import DataTable, { Pagination } from '../components/DataTable';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { fmtDate } from '../utils/format';

const PAGE_SIZE = 10;
const EMPTY_FORM = { name: '', source: '0', location_id: '', active: true };

export default function Cameras() {
  const toast = useToast();
  const { user } = useAuth();
  const canManage = ['admin', 'it'].includes(user?.role);

  const [cameras, setCameras] = useState(null);
  const [locations, setLocations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [locFilter, setLocFilter] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [page, setPage] = useState(1);

  const [editing, setEditing] = useState(null); // null | 'new' | camera
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    Promise.all([api.get('/api/cameras'), api.get('/api/cameras/locations')])
      .then(([cams, locs]) => {
        setCameras(cams || []);
        setLocations(locs || []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const filtered = useMemo(() => {
    let rows = cameras || [];
    if (search) {
      const s = search.toLowerCase();
      rows = rows.filter(
        (c) =>
          c.name.toLowerCase().includes(s) ||
          c.source.toLowerCase().includes(s) ||
          (c.location?.name || '').toLowerCase().includes(s)
      );
    }
    if (locFilter) rows = rows.filter((c) => String(c.location_id) === locFilter);
    if (activeFilter) rows = rows.filter((c) => String(c.active) === activeFilter);
    return rows;
  }, [cameras, search, locFilter, activeFilter]);

  useEffect(() => setPage(1), [search, locFilter, activeFilter]);
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError('');
    setEditing('new');
  };

  const openEdit = (c) => {
    setForm({
      name: c.name,
      source: c.source,
      location_id: c.location_id ?? '',
      active: c.active,
    });
    setFormError('');
    setEditing(c);
  };

  const save = async () => {
    setSaving(true);
    setFormError('');
    try {
      const payload = {
        name: form.name.trim(),
        source: form.source.trim() || '0',
        location_id: form.location_id === '' ? null : Number(form.location_id),
        active: !!form.active,
      };
      if (editing === 'new') {
        await api.post('/api/cameras', payload);
        toast('Camera created', 'success');
      } else {
        await api.put(`/api/cameras/${editing.id}`, payload);
        toast('Camera updated', 'success');
      }
      setEditing(null);
      load();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api.del(`/api/cameras/${deleteTarget.id}`);
      toast('Camera deleted', 'success');
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
          <div className="filter-row">
            <div className="form-field inline">
              <label>Search</label>
              <input
                type="search"
                placeholder="Name, source, location…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="form-field inline">
              <label>Location</label>
              <select value={locFilter} onChange={(e) => setLocFilter(e.target.value)}>
                <option value="">All</option>
                {locations.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field inline">
              <label>Status</label>
              <select value={activeFilter} onChange={(e) => setActiveFilter(e.target.value)}>
                <option value="">All</option>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </div>
          </div>
          {canManage && (
            <button className="btn btn-primary" onClick={openCreate}>
              <Icon name="plus" size={15} /> Add Camera
            </button>
          )}
        </div>

        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'source', label: 'Source' },
            {
              key: 'location_id',
              label: 'Location',
              render: (c) =>
                c.location
                  ? [c.location.name, c.location.building, c.location.room]
                      .filter(Boolean)
                      .join(' · ')
                  : '—',
            },
            {
              key: 'active',
              label: 'Status',
              render: (c) => (
                <Badge value={c.active ? 'online' : 'offline'}>
                  {c.active ? 'Active' : 'Inactive'}
                </Badge>
              ),
            },
            { key: 'created_at', label: 'Added', render: (c) => fmtDate(c.created_at) },
            ...(canManage
              ? [
                  {
                    key: '_actions',
                    label: '',
                    sortable: false,
                    render: (c) => (
                      <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                        <button className="icon-btn" title="Edit" onClick={() => openEdit(c)}>
                          <Icon name="edit" size={15} />
                        </button>
                        <button
                          className="icon-btn danger"
                          title="Delete"
                          onClick={() => setDeleteTarget(c)}
                        >
                          <Icon name="trash" size={15} />
                        </button>
                      </div>
                    ),
                  },
                ]
              : []),
          ]}
          rows={pageRows}
          loading={loading}
          error={error || null}
          emptyTitle="No cameras"
          emptyMessage="Add a camera to start monitoring."
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
      </div>

      <Modal
        open={!!editing}
        title={editing === 'new' ? 'Add Camera' : `Edit ${editing?.name || ''}`}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={save}
              disabled={saving || !form.name.trim()}
            >
              {saving ? 'Saving…' : editing === 'new' ? 'Create Camera' : 'Save Changes'}
            </button>
          </>
        }
      >
        <div className="form-grid">
          <div className="form-field">
            <label>Name</label>
            <input
              value={form.name}
              placeholder="e.g. lobby-cam"
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Source (device index or stream URL)</label>
            <input
              value={form.source}
              placeholder='"0" for built-in webcam, or rtsp://…'
              onChange={(e) => setForm((f) => ({ ...f, source: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Location</label>
            <select
              value={form.location_id}
              onChange={(e) => setForm((f) => ({ ...f, location_id: e.target.value }))}
            >
              <option value="">None</option>
              {locations.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={form.active}
                onChange={(e) => setForm((f) => ({ ...f, active: e.target.checked }))}
              />{' '}
              Active
            </label>
          </div>
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>

      <Modal
        open={!!deleteTarget}
        title="Delete camera?"
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setDeleteTarget(null)}>
              Cancel
            </button>
            <button className="btn btn-danger" onClick={remove}>
              Delete
            </button>
          </>
        }
      >
        <p>
          Camera <strong>{deleteTarget?.name}</strong> will be removed. Recognition logs that
          reference it keep their history.
        </p>
      </Modal>
    </div>
  );
}
