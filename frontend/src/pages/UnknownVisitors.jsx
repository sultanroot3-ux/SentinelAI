import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, asPage } from '../api/client';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icons';
import { Pagination } from '../components/DataTable';
import { useToast } from '../components/Toast';
import { fmtDateTime, titleCase } from '../utils/format';

const STATUSES = ['', 'new', 'reviewed', 'case_opened'];
const PAGE_SIZE = 12;

export default function UnknownVisitors() {
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // open-case modal
  const [caseTarget, setCaseTarget] = useState(null);
  const [caseForm, setCaseForm] = useState({ priority: 'medium', notes: '', assigned_to: '' });
  const [users, setUsers] = useState([]);
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/unknown', { status, page })
      .then((d) => setData(asPage(d)))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [status, page]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get('/api/users')
      .then((d) => setUsers(Array.isArray(d) ? d : d?.items || []))
      .catch(() => {});
  }, []);

  const markReviewed = async (item) => {
    try {
      await api.put(`/api/unknown/${item.id}`, { status: 'reviewed' });
      toast('Marked as reviewed', 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  const openCase = async () => {
    setSaving(true);
    try {
      await api.post('/api/cases', {
        unknown_face_id: caseTarget.id,
        priority: caseForm.priority,
        notes: caseForm.notes,
        assigned_to: caseForm.assigned_to ? Number(caseForm.assigned_to) : null,
      });
      toast('Case opened', 'success');
      setCaseTarget(null);
      setCaseForm({ priority: 'medium', notes: '', assigned_to: '' });
      load();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    try {
      await api.del(`/api/unknown/${deleteTarget.id}`);
      toast('Snapshot deleted', 'success');
      setDeleteTarget(null);
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  const items = data?.items || [];

  return (
    <div className="page">
      <div className="tab-row">
        {STATUSES.map((s) => (
          <button
            key={s || 'all'}
            className={`tab ${status === s ? 'active' : ''}`}
            onClick={() => {
              setStatus(s);
              setPage(1);
            }}
          >
            {s ? titleCase(s) : 'All'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="fullpage-loading">
          <Spinner />
        </div>
      ) : error ? (
        <div className="error-text card pad">{error}</div>
      ) : items.length === 0 ? (
        <div className="card pad">
          <EmptyState
            icon="unknown"
            title="No unknown visitors"
            message="Unrecognized faces captured by the cameras will appear here."
          />
        </div>
      ) : (
        <>
          <div className="unknown-grid">
            {items.map((item) => (
              <div key={item.id} className="card unknown-card">
                <div className="unknown-card-img">
                  {item.snapshot_url ? (
                    <img src={item.snapshot_url} alt="Unknown visitor snapshot" />
                  ) : (
                    <div className="thumb-empty-lg">
                      <Icon name="unknown" size={30} />
                    </div>
                  )}
                </div>
                <div className="unknown-card-body">
                  <div className="unknown-card-meta">
                    <Badge value={item.status} />
                    <span className="muted-text">{item.camera || '—'}</span>
                  </div>
                  <div className="muted-text">{fmtDateTime(item.timestamp)}</div>
                  {item.case_id && <div className="muted-text">Case #{item.case_id}</div>}
                  <div className="unknown-card-actions">
                    <button
                      className="btn btn-ghost btn-sm"
                      onClick={() => navigate(`/investigation?unknown=${item.id}`)}
                    >
                      <Icon name="eye" size={14} /> Investigate
                    </button>
                    {item.status !== 'reviewed' && item.status !== 'case_opened' && (
                      <button className="btn btn-ghost btn-sm" onClick={() => markReviewed(item)}>
                        <Icon name="check" size={14} /> Reviewed
                      </button>
                    )}
                    {item.status !== 'case_opened' && (
                      <button
                        className="btn btn-secondary btn-sm"
                        onClick={() => setCaseTarget(item)}
                      >
                        <Icon name="cases" size={14} /> Open Case
                      </button>
                    )}
                    <button
                      className="btn btn-ghost btn-sm danger"
                      onClick={() => setDeleteTarget(item)}
                    >
                      <Icon name="trash" size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          <Pagination page={page} pageSize={PAGE_SIZE} total={data?.total || 0} onPage={setPage} />
        </>
      )}

      <Modal
        open={!!caseTarget}
        title="Open Investigation Case"
        onClose={() => setCaseTarget(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setCaseTarget(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={openCase} disabled={saving}>
              {saving ? 'Creating…' : 'Create Case'}
            </button>
          </>
        }
      >
        {caseTarget && (
          <div className="form-grid">
            {caseTarget.snapshot_url && (
              <img className="modal-snapshot" src={caseTarget.snapshot_url} alt="" />
            )}
            <div className="form-field">
              <label>Priority</label>
              <select
                value={caseForm.priority}
                onChange={(e) => setCaseForm((f) => ({ ...f, priority: e.target.value }))}
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="critical">Critical</option>
              </select>
            </div>
            <div className="form-field">
              <label>Assign to</label>
              <select
                value={caseForm.assigned_to}
                onChange={(e) => setCaseForm((f) => ({ ...f, assigned_to: e.target.value }))}
              >
                <option value="">Unassigned</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field">
              <label>Notes</label>
              <textarea
                rows={3}
                value={caseForm.notes}
                onChange={(e) => setCaseForm((f) => ({ ...f, notes: e.target.value }))}
                placeholder="Initial observations…"
              />
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={!!deleteTarget}
        title="Delete snapshot?"
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
        <p>This unknown-visitor snapshot will be permanently removed.</p>
      </Modal>
    </div>
  );
}
