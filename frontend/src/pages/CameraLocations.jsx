import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../context/AuthContext';
import DataTable, { Pagination } from '../components/DataTable';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';

const PAGE_SIZE = 10;
const EMPTY_FORM = { name: '', building: '', floor: '', room: '', description: '' };

export default function CameraLocations() {
  const toast = useToast();
  const { user } = useAuth();
  const canManage = ['admin', 'it'].includes(user?.role);

  const [locations, setLocations] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    Promise.all([api.get('/api/cameras/locations'), api.get('/api/cameras')])
      .then(([locs, cams]) => {
        setLocations(locs || []);
        setCameras(cams || []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const cameraCount = useMemo(() => {
    const counts = {};
    for (const c of cameras) {
      if (c.location_id != null) counts[c.location_id] = (counts[c.location_id] || 0) + 1;
    }
    return counts;
  }, [cameras]);

  const filtered = useMemo(() => {
    let rows = locations || [];
    if (search) {
      const s = search.toLowerCase();
      rows = rows.filter((l) =>
        [l.name, l.building, l.floor, l.room, l.description]
          .filter(Boolean)
          .some((v) => v.toLowerCase().includes(s))
      );
    }
    return rows;
  }, [locations, search]);

  useEffect(() => setPage(1), [search]);
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const save = async () => {
    setSaving(true);
    setFormError('');
    try {
      await api.post('/api/cameras/locations', {
        name: form.name.trim(),
        building: form.building.trim() || null,
        floor: form.floor.trim() || null,
        room: form.room.trim() || null,
        description: form.description.trim() || null,
      });
      toast('Location created', 'success');
      setCreating(false);
      setForm(EMPTY_FORM);
      load();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSaving(false);
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
                placeholder="Name, building, room…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>
          {canManage && (
            <button
              className="btn btn-primary"
              onClick={() => {
                setForm(EMPTY_FORM);
                setFormError('');
                setCreating(true);
              }}
            >
              <Icon name="plus" size={15} /> Add Location
            </button>
          )}
        </div>

        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'building', label: 'Building', render: (l) => l.building || '—' },
            { key: 'floor', label: 'Floor', render: (l) => l.floor || '—' },
            { key: 'room', label: 'Room', render: (l) => l.room || '—' },
            {
              key: 'description',
              label: 'Description',
              render: (l) => l.description || '—',
            },
            {
              key: '_cameras',
              label: 'Cameras',
              sortable: false,
              render: (l) => cameraCount[l.id] || 0,
            },
          ]}
          rows={pageRows}
          loading={loading}
          error={error || null}
          emptyTitle="No locations"
          emptyMessage="Add a location, then assign cameras to it."
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
        <p className="muted-text spaced-top">
          Locations can be created and assigned to cameras. Renaming/removing locations is not
          supported by the API.
        </p>
      </div>

      <Modal
        open={creating}
        title="Add Camera Location"
        onClose={() => setCreating(false)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setCreating(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={save}
              disabled={saving || !form.name.trim()}
            >
              {saving ? 'Saving…' : 'Create Location'}
            </button>
          </>
        }
      >
        <div className="form-grid two-col">
          <div className="form-field">
            <label>Name</label>
            <input
              value={form.name}
              placeholder="e.g. East Entrance"
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Building</label>
            <input
              value={form.building}
              onChange={(e) => setForm((f) => ({ ...f, building: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Floor</label>
            <input
              value={form.floor}
              onChange={(e) => setForm((f) => ({ ...f, floor: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Room</label>
            <input
              value={form.room}
              onChange={(e) => setForm((f) => ({ ...f, room: e.target.value }))}
            />
          </div>
        </div>
        <div className="form-field">
          <label>Description</label>
          <input
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
          />
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>
    </div>
  );
}
