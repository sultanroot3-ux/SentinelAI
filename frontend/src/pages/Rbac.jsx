import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import Badge from '../components/Badge';
import Spinner from '../components/Spinner';
import Icon from '../components/Icons';
import { titleCase } from '../utils/format';

/** Read-only RBAC matrix: which role holds which permission. */
export default function Rbac() {
  const [roles, setRoles] = useState(null);
  const [permissions, setPermissions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');

  useEffect(() => {
    setLoading(true);
    Promise.all([api.get('/api/rbac/roles'), api.get('/api/rbac/permissions')])
      .then(([r, p]) => {
        setRoles(r || []);
        setPermissions(p || []);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const grants = useMemo(() => {
    const map = {};
    for (const role of roles || []) {
      map[role.name] = new Set(role.permissions.map((p) => p.code));
    }
    return map;
  }, [roles]);

  const filteredPerms = useMemo(() => {
    if (!search) return permissions;
    const s = search.toLowerCase();
    return permissions.filter(
      (p) =>
        p.code.toLowerCase().includes(s) || (p.description || '').toLowerCase().includes(s)
    );
  }, [permissions, search]);

  if (loading) return <div className="page"><Spinner /></div>;
  if (error) return <div className="page"><div className="error-text">{error}</div></div>;

  return (
    <div className="page">
      <div className="card pad">
        <div className="card-title-row">
          <h2>Roles &amp; Permissions</h2>
          <span className="muted-text">
            Catalogue is seeded by the backend and read-only here.
          </span>
        </div>

        <div className="role-cards">
          {(roles || []).map((r) => (
            <div className="card pad role-card" key={r.id}>
              <h3>
                <Icon name="shield" size={16} /> {titleCase(r.name.replace('_', ' '))}
              </h3>
              <p className="muted-text">{r.description}</p>
              <Badge value="online">{r.permissions.length} permissions</Badge>
            </div>
          ))}
        </div>

        <div className="filter-row spaced-top">
          <div className="form-field inline">
            <label>Search permissions</label>
            <input
              type="search"
              placeholder="Code or description…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
        </div>

        <div className="table-wrap">
          <table className="data-table rbac-matrix">
            <thead>
              <tr>
                <th>Permission</th>
                <th>Description</th>
                {(roles || []).map((r) => (
                  <th key={r.id} className="rbac-role-col">
                    {titleCase(r.name.replace('_', ' '))}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filteredPerms.map((p) => (
                <tr key={p.id}>
                  <td><code>{p.code}</code></td>
                  <td className="muted-text">{p.description}</td>
                  {(roles || []).map((r) => (
                    <td key={r.id} className="rbac-cell">
                      {grants[r.name]?.has(p.code) ? (
                        <span className="rbac-granted"><Icon name="check" size={15} /></span>
                      ) : (
                        <span className="rbac-denied">—</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
