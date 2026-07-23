import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import DataTable, { Pagination } from '../components/DataTable';
import Badge from '../components/Badge';
import { fmtDateTime } from '../utils/format';

const PAGE_SIZE = 25;
const EVENTS = ['detected', 'entry', 'exit', 'check_in', 'check_out'];
const EVENT_BADGE = {
  detected: 'pending',
  entry: 'online',
  exit: 'offline',
  check_in: 'online',
  check_out: 'offline',
};

export default function AccessHistory() {
  const [data, setData] = useState(null);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [userFilter, setUserFilter] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    api
      .get('/api/access-history', {
        page,
        page_size: PAGE_SIZE,
        event: eventFilter || undefined,
        user_id: userFilter || undefined,
      })
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [page, eventFilter, userFilter]);

  useEffect(load, [load]);

  useEffect(() => {
    api
      .get('/api/users')
      .then((rows) => setUsers(Array.isArray(rows) ? rows : []))
      .catch(() => {});
  }, []);

  useEffect(() => setPage(1), [eventFilter, userFilter]);

  const subject = (r) =>
    r.user_name ||
    r.visitor_name ||
    (r.unknown_face_id != null ? `Unknown record #${r.unknown_face_id}` : '—');

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row space-between">
          <div className="filter-row">
            <div className="form-field inline">
              <label>Event</label>
              <select value={eventFilter} onChange={(e) => setEventFilter(e.target.value)}>
                <option value="">All</option>
                {EVENTS.map((ev) => (
                  <option key={ev} value={ev}>
                    {ev.replace('_', ' ')}
                  </option>
                ))}
              </select>
            </div>
            <div className="form-field inline">
              <label>Employee</label>
              <select value={userFilter} onChange={(e) => setUserFilter(e.target.value)}>
                <option value="">All</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
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
            { key: 'user_name', label: 'Subject', render: subject, sortable: false },
            {
              key: 'event',
              label: 'Event',
              render: (r) => (
                <Badge value={EVENT_BADGE[r.event] || 'pending'}>
                  {r.event.replace('_', ' ')}
                </Badge>
              ),
            },
            {
              key: 'camera_name',
              label: 'Camera',
              render: (r) => r.camera_name || '—',
            },
            { key: 'detail', label: 'Detail', render: (r) => r.detail || '—' },
          ]}
          rows={data?.items || []}
          loading={loading}
          error={error || null}
          emptyTitle="No access events"
          emptyMessage="Detections, entries and visitor check-ins will appear here."
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
