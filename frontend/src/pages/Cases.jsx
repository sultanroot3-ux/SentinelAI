import { useCallback, useEffect, useState } from 'react';
import { api, asPage } from '../api/client';
import DataTable, { Pagination } from '../components/DataTable';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import { useToast } from '../components/Toast';
import { fmtDateTime } from '../utils/format';

const PAGE_SIZE = 20;

export default function Cases() {
  const toast = useToast();
  const [filters, setFilters] = useState({ status: '', priority: '' });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [users, setUsers] = useState([]);

  const [selected, setSelected] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/cases', { status: filters.status, priority: filters.priority, page })
      .then((d) => setData(asPage(d)))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [filters, page]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get('/api/users')
      .then((d) => setUsers(Array.isArray(d) ? d : d?.items || []))
      .catch(() => {});
  }, []);

  const openDetail = async (row) => {
    setSelected(row);
    setForm({
      status: row.status || 'open',
      priority: row.priority || 'medium',
      notes: row.notes || '',
      assigned_to: row.assigned_to ?? '',
      resolution: row.resolution || '',
    });
    // Refresh full record in the background.
    try {
      const full = await api.get(`/api/cases/${row.id}`);
      setSelected(full);
      setForm({
        status: full.status || 'open',
        priority: full.priority || 'medium',
        notes: full.notes || '',
        assigned_to: full.assigned_to ?? '',
        resolution: full.resolution || '',
      });
    } catch {
      /* keep row data */
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/api/cases/${selected.id}`, {
        status: form.status,
        priority: form.priority,
        notes: form.notes,
        assigned_to: form.assigned_to === '' ? null : Number(form.assigned_to),
        resolution: form.resolution,
      });
      toast('Case updated', 'success');
      setSelected(null);
      load();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row">
          <div className="form-field inline">
            <label>Status</label>
            <select
              value={filters.status}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, status: e.target.value }));
              }}
            >
              <option value="">All</option>
              <option value="open">Open</option>
              <option value="investigating">Investigating</option>
              <option value="closed">Closed</option>
            </select>
          </div>
          <div className="form-field inline">
            <label>Priority</label>
            <select
              value={filters.priority}
              onChange={(e) => {
                setPage(1);
                setFilters((f) => ({ ...f, priority: e.target.value }));
              }}
            >
              <option value="">All</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="critical">Critical</option>
            </select>
          </div>
        </div>

        <DataTable
          columns={[
            {
              key: 'snapshot_url',
              label: '',
              sortable: false,
              width: 52,
              render: (r) =>
                r.snapshot_url ? (
                  <img className="thumb" src={r.snapshot_url} alt="" />
                ) : (
                  <span className="thumb thumb-empty" />
                ),
            },
            { key: 'case_number', label: 'Case #' },
            { key: 'camera', label: 'Camera' },
            { key: 'status', label: 'Status', render: (r) => <Badge value={r.status} /> },
            { key: 'priority', label: 'Priority', render: (r) => <Badge value={r.priority} /> },
            {
              key: 'assigned_to_name',
              label: 'Assigned To',
              render: (r) => r.assigned_to_name || 'Unassigned',
            },
            { key: 'created_at', label: 'Created', render: (r) => fmtDateTime(r.created_at) },
            { key: 'updated_at', label: 'Updated', render: (r) => fmtDateTime(r.updated_at) },
          ]}
          rows={data?.items || []}
          loading={loading}
          error={error || null}
          emptyTitle="No cases"
          emptyMessage="Open a case from the Unknown Visitors page."
          onRowClick={openDetail}
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={data?.total || 0} onPage={setPage} />
      </div>

      <Modal
        open={!!selected}
        title={selected ? `Case ${selected.case_number || `#${selected.id}`}` : ''}
        onClose={() => setSelected(null)}
        wide
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setSelected(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </>
        }
      >
        {selected && form && (
          <div className="case-detail">
            {selected.snapshot_url && (
              <img className="modal-snapshot" src={selected.snapshot_url} alt="Case snapshot" />
            )}
            <div className="muted-text">
              Camera: {selected.camera || '—'} · Created {fmtDateTime(selected.created_at)}
            </div>
            <div className="form-grid two-col">
              <div className="form-field">
                <label>Status</label>
                <select
                  value={form.status}
                  onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
                >
                  <option value="open">Open</option>
                  <option value="investigating">Investigating</option>
                  <option value="closed">Closed</option>
                </select>
              </div>
              <div className="form-field">
                <label>Priority</label>
                <select
                  value={form.priority}
                  onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
                >
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
              <div className="form-field">
                <label>Assigned to</label>
                <select
                  value={form.assigned_to}
                  onChange={(e) => setForm((f) => ({ ...f, assigned_to: e.target.value }))}
                >
                  <option value="">Unassigned</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="form-field">
              <label>Notes</label>
              <textarea
                rows={3}
                value={form.notes}
                onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))}
              />
            </div>
            <div className="form-field">
              <label>Resolution</label>
              <textarea
                rows={2}
                value={form.resolution}
                onChange={(e) => setForm((f) => ({ ...f, resolution: e.target.value }))}
                placeholder="How was this case resolved?"
              />
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
