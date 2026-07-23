import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import DataTable, { Pagination } from '../components/DataTable';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { fmtDateTime } from '../utils/format';

const PAGE_SIZE = 10;
const EMPTY_FORM = { name: '', company: '', purpose: '', host_user_id: '', badge_number: '' };

const STATUS_BADGE = { expected: 'pending', checked_in: 'online', checked_out: 'offline' };

export default function Visitors() {
  const toast = useToast();
  const [visitors, setVisitors] = useState(null);
  const [hosts, setHosts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  const [editing, setEditing] = useState(null); // null | 'new' | visitor
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null); // {visitor, type}

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/visitors', statusFilter ? { status: statusFilter } : undefined)
      .then((rows) => setVisitors(rows || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get('/api/users')
      .then((rows) => setHosts(Array.isArray(rows) ? rows : []))
      .catch(() => {});
  }, []);

  const filtered = useMemo(() => {
    let rows = visitors || [];
    if (search) {
      const s = search.toLowerCase();
      rows = rows.filter((v) =>
        [v.name, v.company, v.purpose, v.host_name, v.badge_number]
          .filter(Boolean)
          .some((x) => x.toLowerCase().includes(s))
      );
    }
    return rows;
  }, [visitors, search]);

  useEffect(() => setPage(1), [search, statusFilter]);
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError('');
    setEditing('new');
  };

  const openEdit = (v) => {
    setForm({
      name: v.name || '',
      company: v.company || '',
      purpose: v.purpose || '',
      host_user_id: v.host_user_id ?? '',
      badge_number: v.badge_number || '',
    });
    setFormError('');
    setEditing(v);
  };

  const save = async () => {
    setSaving(true);
    setFormError('');
    try {
      const payload = {
        name: form.name.trim(),
        company: form.company.trim() || null,
        purpose: form.purpose.trim() || null,
        host_user_id: form.host_user_id === '' ? null : Number(form.host_user_id),
        badge_number: form.badge_number.trim() || null,
      };
      if (editing === 'new') {
        await api.post('/api/visitors', payload);
        toast('Visitor registered', 'success');
      } else {
        await api.put(`/api/visitors/${editing.id}`, payload);
        toast('Visitor updated', 'success');
      }
      setEditing(null);
      load();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const runAction = async () => {
    const { visitor, type } = confirmAction;
    try {
      await api.post(`/api/visitors/${visitor.id}/${type}`);
      toast(`${visitor.name} ${type === 'check-in' ? 'checked in' : 'checked out'}`, 'success');
      setConfirmAction(null);
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
                placeholder="Name, company, host…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="form-field inline">
              <label>Status</label>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="">All</option>
                <option value="expected">Expected</option>
                <option value="checked_in">Checked in</option>
                <option value="checked_out">Checked out</option>
              </select>
            </div>
          </div>
          <button className="btn btn-primary" onClick={openCreate}>
            <Icon name="plus" size={15} /> Register Visitor
          </button>
        </div>

        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'company', label: 'Company', render: (v) => v.company || '—' },
            { key: 'purpose', label: 'Purpose', render: (v) => v.purpose || '—' },
            { key: 'host_name', label: 'Host', render: (v) => v.host_name || '—' },
            { key: 'badge_number', label: 'Badge', render: (v) => v.badge_number || '—' },
            {
              key: 'status',
              label: 'Status',
              render: (v) => (
                <Badge value={STATUS_BADGE[v.status] || v.status}>
                  {v.status.replace('_', ' ')}
                </Badge>
              ),
            },
            {
              key: 'check_in',
              label: 'Check-in',
              render: (v) => (v.check_in ? fmtDateTime(v.check_in) : '—'),
            },
            {
              key: 'check_out',
              label: 'Check-out',
              render: (v) => (v.check_out ? fmtDateTime(v.check_out) : '—'),
            },
            {
              key: '_actions',
              label: '',
              sortable: false,
              render: (v) => (
                <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                  {v.status !== 'checked_in' && (
                    <button
                      className="icon-btn"
                      title="Check in"
                      onClick={() => setConfirmAction({ visitor: v, type: 'check-in' })}
                    >
                      <Icon name="check" size={15} />
                    </button>
                  )}
                  {v.status === 'checked_in' && (
                    <button
                      className="icon-btn"
                      title="Check out"
                      onClick={() => setConfirmAction({ visitor: v, type: 'check-out' })}
                    >
                      <Icon name="logout" size={15} />
                    </button>
                  )}
                  <button className="icon-btn" title="Edit" onClick={() => openEdit(v)}>
                    <Icon name="edit" size={15} />
                  </button>
                </div>
              ),
            },
          ]}
          rows={pageRows}
          loading={loading}
          error={error || null}
          emptyTitle="No visitors"
          emptyMessage="Register a visitor to get started."
        />
        <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
      </div>

      <Modal
        open={!!editing}
        title={editing === 'new' ? 'Register Visitor' : `Edit ${editing?.name || ''}`}
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
              {saving ? 'Saving…' : editing === 'new' ? 'Register' : 'Save Changes'}
            </button>
          </>
        }
      >
        <div className="form-grid two-col">
          <div className="form-field">
            <label>Full Name</label>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Company</label>
            <input
              value={form.company}
              onChange={(e) => setForm((f) => ({ ...f, company: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Host</label>
            <select
              value={form.host_user_id}
              onChange={(e) => setForm((f) => ({ ...f, host_user_id: e.target.value }))}
            >
              <option value="">None</option>
              {hosts.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>Badge Number</label>
            <input
              value={form.badge_number}
              onChange={(e) => setForm((f) => ({ ...f, badge_number: e.target.value }))}
            />
          </div>
        </div>
        <div className="form-field">
          <label>Purpose of visit</label>
          <input
            value={form.purpose}
            onChange={(e) => setForm((f) => ({ ...f, purpose: e.target.value }))}
          />
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>

      <Modal
        open={!!confirmAction}
        title={confirmAction?.type === 'check-in' ? 'Check in visitor?' : 'Check out visitor?'}
        onClose={() => setConfirmAction(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setConfirmAction(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={runAction}>
              Confirm
            </button>
          </>
        }
      >
        <p>
          <strong>{confirmAction?.visitor?.name}</strong>
          {confirmAction?.visitor?.company ? ` (${confirmAction.visitor.company})` : ''} will be{' '}
          {confirmAction?.type === 'check-in' ? 'checked in' : 'checked out'} and the event recorded
          in access history.
        </p>
      </Modal>
    </div>
  );
}
