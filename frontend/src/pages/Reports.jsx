import { useEffect, useState } from 'react';
import { api } from '../api/client';
import Spinner from '../components/Spinner';
import EmptyState from '../components/EmptyState';
import Icon from '../components/Icons';
import { useToast } from '../components/Toast';
import { titleCase } from '../utils/format';

const PERIODS = ['daily', 'weekly', 'monthly'];

const DOWNLOAD_FORMATS = [
  { format: 'csv', ext: 'csv', label: 'CSV' },
  { format: 'pdf', ext: 'pdf', label: 'PDF' },
  { format: 'xlsx', ext: 'xlsx', label: 'Excel' },
];

export default function Reports() {
  const toast = useToast();
  const [period, setPeriod] = useState('daily');
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState('');

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError('');
    api
      .get('/api/reports/visitors', { period, format: 'json' })
      .then((d) => {
        if (!alive) return;
        const list = Array.isArray(d) ? d : d?.items || d?.rows || d?.data || [];
        setRows(list);
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [period]);

  const download = async (format, ext) => {
    setDownloading(format);
    try {
      const res = await api.raw('/api/reports/visitors', { period, format });
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `visitors_${period}_${new Date().toISOString().slice(0, 10)}.${ext}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast(e.message, 'error');
    } finally {
      setDownloading('');
    }
  };

  const columns = rows && rows.length ? Object.keys(rows[0]) : [];

  return (
    <div className="page">
      <div className="card pad">
        <div className="filter-row space-between">
          <div className="tab-row inline-tabs">
            {PERIODS.map((p) => (
              <button
                key={p}
                className={`tab ${period === p ? 'active' : ''}`}
                onClick={() => setPeriod(p)}
              >
                {titleCase(p)}
              </button>
            ))}
          </div>
          <div className="row-gap">
            {DOWNLOAD_FORMATS.map(({ format, ext, label }) => (
              <button
                key={format}
                className={`btn ${format === 'csv' ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => download(format, ext)}
                disabled={!!downloading}
              >
                <Icon name="reports" size={15} />{' '}
                {downloading === format ? 'Preparing…' : label}
              </button>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="fullpage-loading">
            <Spinner />
          </div>
        ) : error ? (
          <div className="error-text">{error}</div>
        ) : !rows || rows.length === 0 ? (
          <EmptyState
            icon="reports"
            title="No report data"
            message={`No visitor activity recorded for the ${period} period.`}
          />
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c}>{titleCase(c)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={i}>
                    {columns.map((c) => (
                      <td key={c}>
                        {row[c] === null || row[c] === undefined ? '—' : String(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
