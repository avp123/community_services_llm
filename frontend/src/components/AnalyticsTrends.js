import React, { useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { WellnessContext } from './AppStateContextProvider';
import { authenticatedFetch } from '../utils/api';
import '../styles/pages/analytics-trends.css';

const METRICS = [
  { key: 'sessions_active', label: 'Active sessions' },
  { key: 'sessions_started', label: 'Sessions started' },
  { key: 'messages_total', label: 'Total messages' },
  { key: 'messages_user', label: 'User messages' },
  { key: 'messages_assistant', label: 'Assistant messages' },
  { key: 'total_chars', label: 'Total chars' },
  { key: 'avg_chars_per_message', label: 'Avg chars per message' },
  { key: 'tool_calls_total', label: 'External Function calls' },
];

function formatMetricValue(metricKey, value, opts = {}) {
  const n = Number(value || 0);
  if (metricKey === 'avg_chars_per_message') {
    const digits = typeof opts.maxFractionDigits === 'number' ? opts.maxFractionDigits : 2;
    return n.toLocaleString(undefined, { maximumFractionDigits: digits });
  }
  return Math.round(n).toLocaleString();
}

function niceNum(range, round) {
  if (!Number.isFinite(range) || range <= 0) return 1;
  const exponent = Math.floor(Math.log10(range));
  const fraction = range / (10 ** exponent);
  let niceFraction;
  if (round) {
    if (fraction < 1.5) niceFraction = 1;
    else if (fraction < 3) niceFraction = 2;
    else if (fraction < 7) niceFraction = 5;
    else niceFraction = 10;
  } else {
    if (fraction <= 1) niceFraction = 1;
    else if (fraction <= 2) niceFraction = 2;
    else if (fraction <= 5) niceFraction = 5;
    else niceFraction = 10;
  }
  return niceFraction * (10 ** exponent);
}

function buildNiceScale(values, metricKey, targetTicks = 5) {
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const boundedMin = Math.min(0, rawMin);
  const boundedMax = Math.max(1, rawMax);
  const range = niceNum(boundedMax - boundedMin || 1, false);
  const step = niceNum(range / Math.max(2, targetTicks - 1), true);
  let niceMin = Math.floor(boundedMin / step) * step;
  let niceMax = Math.ceil(boundedMax / step) * step;
  if (metricKey !== 'avg_chars_per_message') {
    niceMin = Math.max(0, niceMin);
  }
  if (niceMax <= niceMin) {
    niceMax = niceMin + Math.max(1, step);
  }
  const ticks = [];
  for (let v = niceMin; v <= niceMax + step * 0.5; v += step) {
    ticks.push(v);
  }
  return { min: niceMin, max: niceMax, ticks };
}

function shortWeek(isoDate) {
  try {
    const d = new Date(isoDate);
    if (Number.isNaN(d.getTime())) return isoDate;
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  } catch {
    return isoDate;
  }
}

function weekRangeLabel(isoDate) {
  try {
    const start = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(start.getTime())) return isoDate;
    const end = new Date(start);
    end.setDate(start.getDate() + 6);
    const fmt = (d) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `${fmt(start)} - ${fmt(end)}`;
  } catch {
    return isoDate;
  }
}

function TrendSvg({ rows, metricKey }) {
  const width = 880;
  const height = 280;
  const pad = 36;
  const topHeadroom = 10;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2 - topHeadroom;
  const vals = rows.map((r) => Number(r[metricKey] || 0));
  const { min: minVal, max: maxVal, ticks } = buildNiceScale(vals, metricKey, 5);
  const range = Math.max(1, maxVal - minVal);

  const points = rows.map((r, i) => {
    const x = pad + (i * innerW) / Math.max(1, rows.length - 1);
    const y = pad + topHeadroom + innerH - ((Number(r[metricKey] || 0) - minVal) / range) * innerH;
    return { x, y, label: shortWeek(r.week_start), value: Number(r[metricKey] || 0) };
  });

  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const [hoveredIdx, setHoveredIdx] = useState(null);
  const hovered = hoveredIdx == null ? null : points[hoveredIdx];

  return (
    <div className="analytics-trends-chart-wrap">
      <svg className="analytics-trends-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metricKey} weekly trend`}>
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#c9ced6" />
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#c9ced6" />
        {ticks.map((tickVal, idx) => {
          const t = (tickVal - minVal) / range;
          const y = pad + topHeadroom + innerH - t * innerH;
          const val = formatMetricValue(metricKey, tickVal, {
            maxFractionDigits: metricKey === 'avg_chars_per_message' ? 2 : 0,
          });
          return (
            <g key={idx}>
              <line x1={pad} y1={y} x2={width - pad} y2={y} stroke="#eef1f5" />
              <text x={6} y={y + 4} className="analytics-trends-axis-text">{val}</text>
            </g>
          );
        })}
        <path d={d} fill="none" stroke="#4f46e5" strokeWidth="3" />
        {points.map((p, idx) => (
          <g key={idx}>
            <circle
              cx={p.x}
              cy={p.y}
              r="14"
              fill="transparent"
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
            />
            <circle
              cx={p.x}
              cy={p.y}
              r={hoveredIdx === idx ? 5 : 4}
              fill="#4f46e5"
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
            />
          </g>
        ))}
        {hovered ? (
          <g>
            <rect
              x={Math.min(width - 160, hovered.x + 8)}
              y={Math.max(10, hovered.y - 36)}
              rx="6"
              ry="6"
              width="150"
              height="30"
              fill="#111827"
              opacity="0.92"
            />
            <text
              x={Math.min(width - 152, hovered.x + 16)}
              y={Math.max(29, hovered.y - 17)}
              fill="#fff"
              fontSize="12"
            >
              {`${weekRangeLabel(rows[hoveredIdx]?.week_start)}: ${formatMetricValue(metricKey, hovered.value)}`}
            </text>
          </g>
        ) : null}
        {points.map((p, idx) => (
          <text key={`x-${idx}`} x={p.x} y={height - 10} textAnchor="middle" className="analytics-trends-axis-text">
            {rows.length <= 12 ? weekRangeLabel(rows[idx]?.week_start) : p.label}
          </text>
        ))}
      </svg>
    </div>
  );
}

function AnalyticsTrends() {
  const { user } = useContext(WellnessContext);
  const [weeks, setWeeks] = useState(12);
  const [metricKey, setMetricKey] = useState('messages_total');
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await authenticatedFetch(`/api/analytics/weekly?weeks=${weeks}`);
      const data = await res.json();
      if (!res.ok || !data?.success) {
        setError(data?.detail || 'Failed to load weekly analytics.');
        setRows([]);
      } else {
        setRows(Array.isArray(data.rows) ? data.rows : []);
      }
    } catch (e) {
      setError(e.message || 'Failed to load weekly analytics.');
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [weeks]);

  useEffect(() => {
    load();
  }, [load]);

  const summaryValue = useMemo(() => {
    if (!rows.length) return 0;
    if (metricKey === 'avg_chars_per_message') {
      const totalChars = rows.reduce((acc, r) => acc + Number(r.total_chars || 0), 0);
      const totalMsgs = rows.reduce((acc, r) => acc + Number(r.messages_total || 0), 0);
      return totalMsgs > 0 ? totalChars / totalMsgs : 0;
    }
    return rows.reduce((acc, r) => acc + Number(r[metricKey] || 0), 0);
  }, [rows, metricKey]);

  if (user.username === '' || !user.isAuthenticated) return <Navigate to="/login" />;

  return (
    <div className="analytics-trends-page">
      <header className="analytics-trends-header">
        <div>
          <h1>Usage trends</h1>
          <p>Week-by-week usage patterns for your PeerCoPilot sessions.</p>
        </div>
        <button type="button" onClick={load} className="analytics-trends-refresh" disabled={loading}>
          Refresh
        </button>
      </header>

      <div className="analytics-trends-controls">
        <label>
          Weeks
          <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
            <option value={4}>Last 4</option>
            <option value={8}>Last 8</option>
            <option value={12}>Last 12</option>
            <option value={24}>Last 24</option>
          </select>
        </label>
        <label>
          Metric
          <select value={metricKey} onChange={(e) => setMetricKey(e.target.value)}>
            {METRICS.map((m) => (
              <option key={m.key} value={m.key}>{m.label}</option>
            ))}
          </select>
        </label>
      </div>

      {loading ? <p className="analytics-trends-state">Loading...</p> : null}
      {error ? <p className="analytics-trends-error">{error}</p> : null}

      {!loading && !error && rows.length > 0 ? (
        <>
          <div className="analytics-trends-summary">
            <span>{METRICS.find((m) => m.key === metricKey)?.label || metricKey}</span>
            <strong>{formatMetricValue(metricKey, summaryValue)}</strong>
          </div>
          <TrendSvg rows={rows} metricKey={metricKey} />
          <div className="analytics-trends-table-wrap">
            <table className="analytics-trends-table">
              <thead>
                <tr>
                  <th>Week range</th>
                  <th>Active sessions</th>
                  <th>Sessions started</th>
                  <th>Total msgs</th>
                  <th>User msgs</th>
                  <th>Assistant msgs</th>
                  <th>Avg chars/msg</th>
                  <th>External Function calls (sessions started)</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.week_start}>
                    <td>{weekRangeLabel(r.week_start)}</td>
                    <td>{r.sessions_active}</td>
                    <td>{r.sessions_started}</td>
                    <td>{r.messages_total}</td>
                    <td>{r.messages_user}</td>
                    <td>{r.messages_assistant}</td>
                    <td>{Number(r.avg_chars_per_message || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                    <td>{r.tool_calls_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default AnalyticsTrends;
