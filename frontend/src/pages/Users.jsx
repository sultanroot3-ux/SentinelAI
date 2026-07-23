import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import DataTable from '../components/DataTable';
import Badge from '../components/Badge';
import Modal from '../components/Modal';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { fmtDate } from '../utils/format';

const ROLES = ['admin', 'security_officer', 'receptionist', 'it'];

const EMPTY_FORM = {
  name: '',
  email: '',
  username: '',
  password: '',
  role: 'receptionist',
  department_id: '',
  employee_id: '',
  access_level: '',
  job_title: '',
  office_building: '',
  badge_number: '',
  phone: '',
  status: 'active',
};

export default function Users() {
  const toast = useToast();
  const navigate = useNavigate();
  const [users, setUsers] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [deptFilter, setDeptFilter] = useState('');

  const [editing, setEditing] = useState(null); // null | 'new' | user object
  const [form, setForm] = useState(EMPTY_FORM);
  const [formError, setFormError] = useState('');
  const [saving, setSaving] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [photoTarget, setPhotoTarget] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/users', { search, role: roleFilter, department_id: deptFilter })
      .then((d) => setUsers(Array.isArray(d) ? d : d?.items || []))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [search, roleFilter, deptFilter]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  useEffect(() => {
    api
      .get('/api/departments')
      .then((d) => setDepartments(Array.isArray(d) ? d : d?.items || []))
      .catch(() => {});
  }, []);

  const openCreate = () => {
    setForm(EMPTY_FORM);
    setFormError('');
    setEditing('new');
  };

  const openEdit = (u) => {
    setForm({
      name: u.name || '',
      email: u.email || '',
      username: u.username || '',
      password: '',
      role: u.role || 'receptionist',
      department_id: u.department_id ?? '',
      employee_id: u.employee_id || '',
      access_level: u.access_level ?? '',
      job_title: u.job_title || '',
      office_building: u.office_building || '',
      badge_number: u.badge_number || '',
      phone: u.phone || '',
      status: u.status || 'active',
    });
    setFormError('');
    setEditing(u);
  };

  const save = async () => {
    setSaving(true);
    setFormError('');
    try {
      const payload = {
        name: form.name,
        email: form.email,
        username: form.username,
        role: form.role,
        department_id: form.department_id === '' ? null : Number(form.department_id),
        employee_id: form.employee_id,
        access_level: form.access_level === '' ? null : String(form.access_level),
        job_title: form.job_title.trim() || null,
        office_building: form.office_building.trim() || null,
        badge_number: form.badge_number.trim() || null,
        phone: form.phone.trim() || null,
        status: form.status,
      };
      if (editing === 'new') {
        payload.password = form.password;
        await api.post('/api/users', payload);
        toast('User created', 'success');
      } else {
        if (form.password) payload.password = form.password;
        await api.put(`/api/users/${editing.id}`, payload);
        toast('User updated', 'success');
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
      await api.del(`/api/users/${deleteTarget.id}`);
      toast('User deleted', 'success');
      setDeleteTarget(null);
      load();
    } catch (e) {
      toast(e.message, 'error');
    }
  };

  const pickPhoto = (u) => {
    setPhotoTarget(u);
    fileRef.current?.click();
  };

  const uploadPhoto = async (file) => {
    if (!file || !photoTarget) return;
    try {
      await api.upload(`/api/users/${photoTarget.id}/photo`, file);
      toast(`Photo uploaded — face registered for ${photoTarget.name}`, 'success');
      load();
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setPhotoTarget(null);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="page">
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        hidden
        onChange={(e) => uploadPhoto(e.target.files?.[0])}
      />

      <div className="card pad">
        <div className="filter-row space-between">
          <div className="filter-row">
            <div className="form-field inline">
              <label>Search</label>
              <input
                type="search"
                placeholder="Name, email, username…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="form-field inline">
              <label>Role</label>
              <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                <option value="">All</option>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r.replace('_', ' ')}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field inline">
              <label>Department</label>
              <select value={deptFilter} onChange={(e) => setDeptFilter(e.target.value)}>
                <option value="">All</option>
                {departments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button className="btn btn-primary" onClick={openCreate}>
            <Icon name="plus" size={15} /> Add User
          </button>
        </div>

        <DataTable
          columns={[
            {
              key: 'photo_url',
              label: '',
              sortable: false,
              width: 52,
              render: (u) => (
                <span className="avatar avatar-table">
                  {u.photo_url ? <img src={u.photo_url} alt="" /> : (u.name || '?').charAt(0)}
                </span>
              ),
            },
            { key: 'name', label: 'Name' },
            { key: 'username', label: 'Username' },
            { key: 'email', label: 'Email' },
            { key: 'role', label: 'Role', render: (u) => <Badge value={u.role} /> },
            {
              key: 'department_name',
              label: 'Department',
              render: (u) => u.department_name || '—',
            },
            { key: 'employee_id', label: 'Employee ID' },
            { key: 'job_title', label: 'Job Title', render: (u) => u.job_title || '—' },
            {
              key: 'badge_number',
              label: 'Badge',
              render: (u) => u.badge_number || '—',
            },
            { key: 'access_level', label: 'Access' },
            {
              key: 'status',
              label: 'Status',
              render: (u) => (
                <Badge value={u.status === 'active' ? 'online' : 'offline'}>
                  {u.status || 'active'}
                </Badge>
              ),
            },
            {
              key: 'face_registered',
              label: 'Face',
              render: (u) => (
                <Badge value={u.face_registered ? 'yes' : 'no'}>
                  {u.face_registered ? 'Registered' : 'Not registered'}
                </Badge>
              ),
            },
            { key: 'created_at', label: 'Created', render: (u) => fmtDate(u.created_at) },
            {
              key: '_actions',
              label: '',
              sortable: false,
              render: (u) => (
                <div className="row-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    className="icon-btn"
                    title="Investigation report"
                    onClick={() => navigate(`/investigation?employee=${u.id}`)}
                  >
                    <Icon name="eye" size={15} />
                  </button>
                  <button className="icon-btn" title="Upload photo" onClick={() => pickPhoto(u)}>
                    <Icon name="upload" size={15} />
                  </button>
                  <button className="icon-btn" title="Edit" onClick={() => openEdit(u)}>
                    <Icon name="edit" size={15} />
                  </button>
                  <button
                    className="icon-btn danger"
                    title="Delete"
                    onClick={() => setDeleteTarget(u)}
                  >
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              ),
            },
          ]}
          rows={users || []}
          loading={loading}
          error={error || null}
          emptyTitle="No users found"
        />
      </div>

      <Modal
        open={!!editing}
        title={editing === 'new' ? 'Add User' : `Edit ${editing?.name || ''}`}
        onClose={() => setEditing(null)}
        wide
        footer={
          <>
            <button className="btn btn-ghost" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : editing === 'new' ? 'Create User' : 'Save Changes'}
            </button>
          </>
        }
      >
        <div className="form-grid two-col">
          <div className="form-field">
            <label>Full Name</label>
            <input value={form.name} onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="form-field">
            <label>Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Username</label>
            <input
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>{editing === 'new' ? 'Password' : 'New Password (leave blank to keep)'}</label>
            <input
              type="password"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              autoComplete="new-password"
            />
          </div>
          <div className="form-field">
            <label>Role</label>
            <select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r.replace('_', ' ')}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>Department</label>
            <select
              value={form.department_id}
              onChange={(e) => setForm((f) => ({ ...f, department_id: e.target.value }))}
            >
              <option value="">None</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-field">
            <label>Employee ID</label>
            <input
              value={form.employee_id}
              onChange={(e) => setForm((f) => ({ ...f, employee_id: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Access Level</label>
            <input
              value={form.access_level}
              placeholder="e.g. full, standard, restricted"
              onChange={(e) => setForm((f) => ({ ...f, access_level: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Job Title</label>
            <input
              value={form.job_title}
              onChange={(e) => setForm((f) => ({ ...f, job_title: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Office / Building</label>
            <input
              value={form.office_building}
              onChange={(e) => setForm((f) => ({ ...f, office_building: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Badge Number</label>
            <input
              value={form.badge_number}
              onChange={(e) => setForm((f) => ({ ...f, badge_number: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Phone</label>
            <input
              type="tel"
              value={form.phone}
              onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
            />
          </div>
          <div className="form-field">
            <label>Status</label>
            <select
              value={form.status}
              onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
            >
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
            </select>
          </div>
        </div>
        {formError && <div className="error-text spaced-top">{formError}</div>}
      </Modal>

      <Modal
        open={!!deleteTarget}
        title="Delete user?"
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
          <strong>{deleteTarget?.name}</strong> ({deleteTarget?.username}) will be permanently
          removed, including their registered face data.
        </p>
      </Modal>
    </div>
  );
}
