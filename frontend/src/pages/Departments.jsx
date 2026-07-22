import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import DataTable from '../components/DataTable';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';

export default function Departments() {
  const toast = useToast();
  const [departments, setDepartments] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const [editing, setEditing] = useState(null); // null | 'new' | dept
  const [form, setForm] = useState({ name: '', description: '' });
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/departments')
      .then((d) => setDepartments(Array.isArray(d) ? d : d?.items || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  const save = async () => {
    setSaving(true);
    setFormError('');
    try {
      if (editing === 'new') {
        await api.post('/api/departments', form);
        toast('Department created', 'success');
      } else {
        await api.put(`/api/departments/${editing.id}`, form);
        toast('Department updated', 'success');
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
      await api.del(`/api/departments/${deleteTarget.id}`);
      toast('Department deleted', 'success');
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
          <h2>Departments</h2>
          <button
            className="btn btn-primary"
            onClick={() => {
              setForm({ name: '', description: '' });
              setFormError('');
              setEditing('new');
            }}
          >
            <Icon name="plus" size={15} /> Add Department
          </button>
        </div>

        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'description', label: 'Description', render: (d) => d.description || '—' },
            { key: 'user_count', label: 'Users' },
            {
              key: '_actions',
              label: '',
              sortable: false,
              width: 90,
              render: (d) => (
                <div className="row-actions">
                  <button
                    className="icon-btn"
                    title="Edit"
                    onClick={() => {
                      setForm({ name: d.name || '', description: d.description || '' });
                      setFormError('');
                      setEditing(d);
                    }}
                  >
                    <Icon name="edit" size={15} />
                  </button>
                  <button
                    className="icon-btn danger"
                    title="Delete"
                    onClick={() => setDeleteTarget(d)}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              ),
            },
          ]}
          rows={departments || []}
          loading={loading}
          error={error || null}
          emptyTitle="No departments"
        />
      </div>

      <Modal
        open={!!editing}
        title={editing === 'new' ? 'Add Department' : 'Edit Department'}
        onClose={() => setEditing(null)}
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !form.name}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </>
        }
      >
        <div className="form-grid">
          <div className="form-field">
            <label>Name</label>
            <input
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              autoFocus
            />
          </div>
          <div className="form-field">
            <label>Description</label>
            <textarea
              rows={3}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </div>
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>

      <Modal
        open={!!deleteTarget}
        title="Delete department?"
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
          <strong>{deleteTarget?.name}</strong> will be removed.
          {deleteTarget?.user_count > 0 && (
            <> It currently has {deleteTarget.user_count} user(s) assigned.</>
          )}
        </p>
      </Modal>
    </div>
  );
}
