import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import DataTable, { Pagination } from '../components/DataTable';
import Badge from '../components/Badge';
import { fmtDateTime } from '../utils/format';

const PAGE_SIZE = 25;

export default function AuditLogs() {
  const [data, setData] = useState(null);
  const [actions, setActions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [actionFilter, setActionFilter] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/audit', {
        page,
        page_size: PAGE_SIZE,
        action: actionFilter || undefined,
        search: search || undefined,
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, actionFilter, search]);

  useEffect(() => {
    const t = setTimeout(load, search ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, search]);

  useEffect(() => {
    api.get('/api/audit/actions').then((a) => setActions(a || [])).catch(() => {});
  }, []);

  useEffect(() => setPage(1), [search, actionFilter]);

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row space-between">
          <div className="filter-row">
            <div className="form-field inline">
              <label>Search</label>
              <input
                type="search"
                placeholder="Detail or username…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="form-field inline">
              <label>Action</label>
              <select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
                <option value="">All</option>
                {actions.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <span className="muted-text">{data?.total ?? 0} events</span>
        </div>

        <DataTable
          columns={[
            {
              key: 'timestamp',
              label: 'Time',
              render: (r) => fmtDateTime(r.timestamp),
              width: 170,
            },
            {
              key: 'username',
              label: 'User',
              render: (r) => r.username || '—',
            },
            {
              key: 'action',
              label: 'Action',
              render: (r) => <Badge value="pending">{r.action}</Badge>,
            },
            { key: 'detail', label: 'Detail', render: (r) => r.detail || '—' },
          ]}
          rows={data?.items || []}
          loading={loading}
          error={error || null}
          emptyTitle="No audit events"
          emptyMessage="Administrative actions will appear here."
        />
        <Pagination
          page={page}
          pageSize={PAGE_SIZE}
          total={data?.total || 0}
          onPage={setPage}
        />
      </div>
    </div>
  );
}
