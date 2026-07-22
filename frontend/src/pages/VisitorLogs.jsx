import { useEffect, useState } from 'react';
import { api, asPage } from '../api/client';
import DataTable, { Pagination } from '../components/DataTable';
import { fmtDateTime, fmtScore } from '../utils/format';

const PAGE_SIZE = 20;

export default function VisitorLogs() {
  const [filters, setFilters] = useState({ date_from: '', date_to: '' });
  const [page, setPage] = useState(1);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    api
      .get('/api/logs', {
        date_from: filters.date_from,
        date_to: filters.date_to,
        page,
        page_size: PAGE_SIZE,
      })
      .then((d) => alive && setData(asPage(d)))
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [filters, page]);

  const setFilter = (key, value) => {
    setPage(1);
    setFilters((f) => ({ ...f, [key]: value }));
  };

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row">
          <div className="form-field inline">
            <label>From</label>
            <input
              type="date"
              value={filters.date_from}
              onChange={(e) => setFilter('date_from', e.target.value)}
            />
          </div>
          <div className="form-field inline">
            <label>To</label>
            <input
              type="date"
              value={filters.date_to}
              onChange={(e) => setFilter('date_to', e.target.value)}
            />
          </div>
          {(filters.date_from || filters.date_to) && (
            <button
              className="btn btn-ghost"
              onClick={() => {
                setPage(1);
                setFilters({ date_from: '', date_to: '' });
              }}
            >
              Clear filters
            </button>
          )}
        </div>

        <DataTable
          columns={[
            {
              key: 'snapshot_url',
              label: 'Snapshot',
              sortable: false,
              width: 70,
              render: (r) =>
                r.snapshot_url ? (
                  <img className="thumb" src={r.snapshot_url} alt="" />
                ) : (
                  <span className="thumb thumb-empty" />
                ),
            },
            { key: 'user_name', label: 'Person', render: (r) => r.user_name || 'Unknown' },
            { key: 'camera', label: 'Camera' },
            { key: 'score', label: 'Score', render: (r) => fmtScore(r.score) },
            { key: 'timestamp', label: 'Timestamp', render: (r) => fmtDateTime(r.timestamp) },
          ]}
          rows={data?.items || []}
          loading={loading}
          error={error || null}
          emptyTitle="No visitor logs"
          emptyMessage="No recognition events match the selected dates."
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
