import { useEffect, useState } from 'react';
import { api } from '../api/client';
import Spinner from '../components/Spinner';
import { LineChart, BarChart, HBarList } from '../components/Charts';

const DAILY_SERIES = [
  { key: 'recognized', label: 'Recognized', color: '--chart-1' },
  { key: 'unknown', label: 'Unknown', color: '--chart-2' },
];

export default function Analytics() {
  const [days, setDays] = useState(14);
  const [daily, setDaily] = useState(null);
  const [peak, setPeak] = useState(null);
  const [cameras, setCameras] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    api
      .get('/api/analytics/daily', { days })
      .then((d) => alive && setDaily(d || []))
      .catch((e) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [days]);

  useEffect(() => {
    let alive = true;
    Promise.allSettled([api.get('/api/analytics/peak-hours'), api.get('/api/analytics/cameras')]).then(
      ([p, c]) => {
        if (!alive) return;
        setPeak(p.status === 'fulfilled' ? p.value || [] : []);
        setCameras(c.status === 'fulfilled' ? c.value || [] : []);
        if (p.status === 'rejected') setError(p.reason?.message || 'Failed to load analytics');
      }
    );
    return () => {
      alive = false;
    };
  }, []);

  const peakData = (peak || []).map((d) => ({
    ...d,
    hour_label: `${String(d.hour).padStart(2, '0')}:00`,
  }));

  return (
    <div className="page">
      {error && <div className="error-text card pad">{error}</div>}

      <div className="card pad">
        <div className="card-title-row">
          <h2>Daily Traffic</h2>
          <div className="tab-row inline-tabs">
            {[7, 14, 30].map((d) => (
              <button key={d} className={`tab ${days === d ? 'active' : ''}`} onClick={() => setDays(d)}>
                {d}d
              </button>
            ))}
          </div>
        </div>
        {daily === null ? (
          <Spinner />
        ) : (
          <LineChart
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
            <h2>Peak Hours</h2>
          </div>
          {peak === null ? (
            <Spinner />
          ) : (
            <BarChart
              data={peakData}
              xKey="hour_label"
              series={[{ key: 'count', label: 'Visits', color: '--chart-1' }]}
              height={220}
            />
          )}
        </div>

        <div className="card pad">
          <div className="card-title-row">
            <h2>Camera Breakdown</h2>
          </div>
          {cameras === null ? (
            <Spinner />
          ) : (
            <HBarList data={cameras} labelKey="camera" valueKey="count" />
          )}
        </div>
      </div>
    </div>
  );
}
