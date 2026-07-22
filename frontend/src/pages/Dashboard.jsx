import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, asPage } from '../api/client';
import StatCard from '../components/StatCard';
import DataTable from '../components/DataTable';
import Badge from '../components/Badge';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';
import { BarChart } from '../components/Charts';
import { fmtDateTime, fmtScore, fmtPercent } from '../utils/format';

const DAILY_SERIES = [
  { key: 'recognized', label: 'Recognized', color: '--chart-1' },
  { key: 'unknown', label: 'Unknown', color: '--chart-2' },
];

export default function Dashboard() {
  const [summary, setSummary] = useState(null);
  const [daily, setDaily] = useState(null);
  const [logs, setLogs] = useState(null);
  const [cases, setCases] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    Promise.allSettled([
      api.get('/api/analytics/summary'),
      api.get('/api/analytics/daily', { days: 7 }),
      api.get('/api/logs', { page: 1, page_size: 8 }),
      api.get('/api/cases', { status: 'open' }),
    ]).then(([s, d, l, c]) => {
      if (!alive) return;
      if (s.status === 'fulfilled') setSummary(s.value);
      else setError(s.reason?.message || 'Failed to load dashboard');
      setDaily(d.status === 'fulfilled' ? d.value : []);
      setLogs(l.status === 'fulfilled' ? asPage(l.value).items : []);
      setCases(c.status === 'fulfilled' ? asPage(c.value).items : []);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (error && !summary) {
    return <div className="error-text card pad">{error}</div>;
  }
  if (!summary) {
    return (
      <div className="fullpage-loading">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="page">
      <div className="stat-grid">
        <StatCard icon="users" label="Total Users" value={summary.total_users ?? 0} tone="accent" />
        <StatCard icon="logs" label="Today's Visitors" value={summary.today_visitors ?? 0} tone="ok" />
        <StatCard
          icon="unknown"
          label="Unknown Today"
          value={summary.today_unknown ?? 0}
          tone="warn"
        />
        <StatCard icon="cases" label="Open Cases" value={summary.open_cases ?? 0} tone="danger" />
        <StatCard
          icon="analytics"
          label="Recognition Accuracy"
          value={fmtPercent(summary.recognition_accuracy)}
          tone="info"
        />
      </div>

      <div className="card pad">
        <div className="card-title-row">
          <h2>Visitors — last 7 days</h2>
          <Link to="/analytics" className="link-sm">
            Full analytics →
          </Link>
        </div>
        {daily === null ? (
          <Spinner />
        ) : (
          <BarChart
            data={daily}
            xKey="date"
            series={DAILY_SERIES}
            xFormat={(d) => String(d).slice(5)}
          />
        )}
      </div>

      <div className="dash-columns">
        <div className="card pad">
          <div className="card-title-row">
            <h2>Recent Visitor Logs</h2>
            <Link to="/logs" className="link-sm">
              View all →
            </Link>
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
              { key: 'user_name', label: 'Person', render: (r) => r.user_name || 'Unknown' },
              { key: 'camera', label: 'Camera' },
              { key: 'score', label: 'Score', render: (r) => fmtScore(r.score) },
              { key: 'timestamp', label: 'Time', render: (r) => fmtDateTime(r.timestamp) },
            ]}
            rows={logs || []}
            loading={logs === null}
            emptyTitle="No visitor logs yet"
          />
        </div>

        <div className="card pad">
          <div className="card-title-row">
            <h2>Open Cases</h2>
            <Link to="/cases" className="link-sm">
              View all →
            </Link>
          </div>
          {cases === null ? (
            <Spinner />
          ) : cases.length === 0 ? (
            <EmptyState icon="cases" title="No open cases" message="All investigations resolved." />
          ) : (
            <ul className="case-list">
              {cases.slice(0, 6).map((c) => (
                <li key={c.id} className="case-list-item">
                  <div>
                    <strong>{c.case_number}</strong>
                    <span className="case-list-meta">
                      {c.camera || '—'} · {fmtDateTime(c.created_at)}
                    </span>
                  </div>
                  <Badge value={c.priority} />
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
