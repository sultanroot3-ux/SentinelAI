import { useState } from 'react';

/* Plain-SVG charts. Series colors come from CSS variables --chart-1 / --chart-2
   (validated for CVD separation and contrast on both theme surfaces). */

const W = 640;
const PAD = { top: 14, right: 12, bottom: 26, left: 40 };

function niceMax(v) {
  if (v <= 5) return 5;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  const norm = v / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}

function Legend({ series }) {
  if (series.length < 2) return null;
  return (
    <div className="chart-legend">
      {series.map((s) => (
        <span key={s.key} className="chart-legend-item">
          <span className="chart-legend-dot" style={{ background: `var(${s.color})` }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

function Tooltip({ hover, data, xKey, series, count }) {
  if (hover == null || !data[hover]) return null;
  const row = data[hover];
  const leftPct = ((hover + 0.5) / count) * 100;
  return (
    <div
      className="chart-tooltip"
      style={{ left: `${leftPct}%`, transform: `translateX(${leftPct > 70 ? '-100%' : '-50%'})` }}
    >
      <div className="chart-tooltip-title">{row[xKey]}</div>
      {series.map((s) => (
        <div key={s.key} className="chart-tooltip-row">
          <span className="chart-legend-dot" style={{ background: `var(${s.color})` }} />
          <span>{s.label}</span>
          <strong>{row[s.key] ?? 0}</strong>
        </div>
      ))}
    </div>
  );
}

function Grid({ max, height, plotW }) {
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  return (
    <>
      {ticks.map((t) => {
        const y = PAD.top + (height - PAD.top - PAD.bottom) * (1 - t);
        return (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={PAD.left + plotW}
              y1={y}
              y2={y}
              className="chart-grid-line"
            />
            <text x={PAD.left - 8} y={y + 4} textAnchor="end" className="chart-axis-text">
              {Math.round(max * t)}
            </text>
          </g>
        );
      })}
    </>
  );
}

/** Grouped vertical bars; 1..2 series. */
export function BarChart({ data = [], xKey, series, height = 240, xFormat }) {
  const [hover, setHover] = useState(null);
  if (!data.length) return <div className="chart-empty">No data</div>;

  const plotW = W - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0))));
  const groupW = plotW / data.length;
  const barGap = 2;
  const barW = Math.min(26, (groupW - 8) / series.length - barGap);
  const labelEvery = Math.ceil(data.length / 10);

  return (
    <div className="chart-box">
      <Legend series={series} />
      <div className="chart-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${height}`} className="chart-svg" role="img">
          <Grid max={max} height={height} plotW={plotW} />
          {data.map((d, i) => {
            const cx = PAD.left + groupW * i + groupW / 2;
            const totalW = series.length * barW + (series.length - 1) * barGap;
            return (
              <g key={i}>
                {series.map((s, si) => {
                  const v = Number(d[s.key]) || 0;
                  const h = (v / max) * plotH;
                  const x = cx - totalW / 2 + si * (barW + barGap);
                  const y = PAD.top + plotH - h;
                  return (
                    <rect
                      key={s.key}
                      x={x}
                      y={y}
                      width={barW}
                      height={Math.max(h, v > 0 ? 2 : 0)}
                      rx={3}
                      fill={`var(${s.color})`}
                      opacity={hover == null || hover === i ? 1 : 0.45}
                    />
                  );
                })}
                {i % labelEvery === 0 && (
                  <text x={cx} y={height - 8} textAnchor="middle" className="chart-axis-text">
                    {xFormat ? xFormat(d[xKey]) : d[xKey]}
                  </text>
                )}
                <rect
                  x={PAD.left + groupW * i}
                  y={PAD.top}
                  width={groupW}
                  height={plotH}
                  fill="transparent"
                  onMouseEnter={() => setHover(i)}
                />
              </g>
            );
          })}
          <line
            x1={PAD.left}
            x2={PAD.left + plotW}
            y1={PAD.top + plotH}
            y2={PAD.top + plotH}
            className="chart-baseline"
          />
        </svg>
        <Tooltip hover={hover} data={data} xKey={xKey} series={series} count={data.length} />
      </div>
    </div>
  );
}

/** Multi-series line chart with crosshair hover. */
export function LineChart({ data = [], xKey, series, height = 240, xFormat }) {
  const [hover, setHover] = useState(null);
  if (!data.length) return <div className="chart-empty">No data</div>;

  const plotW = W - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const max = niceMax(Math.max(1, ...data.flatMap((d) => series.map((s) => Number(d[s.key]) || 0))));
  const px = (i) => PAD.left + (data.length === 1 ? plotW / 2 : (plotW * i) / (data.length - 1));
  const py = (v) => PAD.top + plotH - ((Number(v) || 0) / max) * plotH;
  const labelEvery = Math.ceil(data.length / 10);

  return (
    <div className="chart-box">
      <Legend series={series} />
      <div className="chart-plot" onMouseLeave={() => setHover(null)}>
        <svg viewBox={`0 0 ${W} ${height}`} className="chart-svg" role="img">
          <Grid max={max} height={height} plotW={plotW} />
          {hover != null && (
            <line
              x1={px(hover)}
              x2={px(hover)}
              y1={PAD.top}
              y2={PAD.top + plotH}
              className="chart-crosshair"
            />
          )}
          {series.map((s) => (
            <polyline
              key={s.key}
              points={data.map((d, i) => `${px(i)},${py(d[s.key])}`).join(' ')}
              fill="none"
              stroke={`var(${s.color})`}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          ))}
          {hover != null &&
            series.map((s) => (
              <circle
                key={s.key}
                cx={px(hover)}
                cy={py(data[hover][s.key])}
                r="4"
                fill={`var(${s.color})`}
                className="chart-point"
              />
            ))}
          {data.map(
            (d, i) =>
              i % labelEvery === 0 && (
                <text key={i} x={px(i)} y={height - 8} textAnchor="middle" className="chart-axis-text">
                  {xFormat ? xFormat(d[xKey]) : d[xKey]}
                </text>
              )
          )}
          <line
            x1={PAD.left}
            x2={PAD.left + plotW}
            y1={PAD.top + plotH}
            y2={PAD.top + plotH}
            className="chart-baseline"
          />
          {data.map((d, i) => (
            <rect
              key={i}
              x={px(i) - plotW / data.length / 2}
              y={PAD.top}
              width={plotW / data.length}
              height={plotH}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
          ))}
        </svg>
        <Tooltip hover={hover} data={data} xKey={xKey} series={series} count={data.length} />
      </div>
    </div>
  );
}

/** Horizontal bar list (HTML) for categorical breakdowns. */
export function HBarList({ data = [], labelKey, valueKey, color = '--chart-1' }) {
  if (!data.length) return <div className="chart-empty">No data</div>;
  const max = Math.max(1, ...data.map((d) => Number(d[valueKey]) || 0));
  return (
    <div className="hbar-list">
      {data.map((d, i) => {
        const v = Number(d[valueKey]) || 0;
        return (
          <div key={i} className="hbar-row" title={`${d[labelKey]}: ${v}`}>
            <span className="hbar-label">{d[labelKey]}</span>
            <span className="hbar-track">
              <span
                className="hbar-fill"
                style={{ width: `${(v / max) * 100}%`, background: `var(${color})` }}
              />
            </span>
            <span className="hbar-value">{v}</span>
          </div>
        );
      })}
    </div>
  );
}
