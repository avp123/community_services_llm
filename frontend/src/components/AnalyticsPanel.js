import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { authenticatedFetch } from '../utils/api';
import { getExternalFunctionLabel } from '../utils/externalFunctionLabels';
import '../styles/components/analytics-panel.css';

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

const PERIOD_OPTIONS = {
  day: [14, 30],
  week: [4, 8, 12, 24],
  month: [3, 6, 12],
};

function formatDate(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

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

function formatBucketLabel(isoDate, granularity) {
  try {
    const d = new Date(`${isoDate}T00:00:00`);
    if (Number.isNaN(d.getTime())) return isoDate;
    if (granularity === 'day') {
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    }
    if (granularity === 'month') {
      return d.toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
    }
    const end = new Date(d);
    end.setDate(d.getDate() + 6);
    const fmt = (v) => v.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    return `${fmt(d)} - ${fmt(end)}`;
  } catch {
    return isoDate;
  }
}

const FEEDBACK_SHORT = {
  q1: 'Effectiveness',
  q2: 'Human connection',
};

function formatLikert(v) {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return '—';
  return n.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
}

function buildDisconnectedPath(rows, key, pad, topHeadroom, innerH, innerW) {
  let d = '';
  let penUp = true;
  rows.forEach((r, i) => {
    const raw = r[key];
    if (raw == null || raw === '') {
      penUp = true;
      return;
    }
    const v = Number(raw);
    if (Number.isNaN(v)) {
      penUp = true;
      return;
    }
    const x = pad + (i * innerW) / Math.max(1, rows.length - 1);
    const y = pad + topHeadroom + innerH - ((v - 1) / 4) * innerH;
    if (penUp) {
      d += `${d ? ' ' : ''}M ${x} ${y}`;
      penUp = false;
    } else {
      d += ` L ${x} ${y}`;
    }
  });
  return d;
}

function FeedbackTrendSvg({ rows, granularity }) {
  const width = 880;
  const height = 300;
  const pad = 36;
  const topHeadroom = 10;
  const legendH = 28;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2 - topHeadroom - legendH;
  const minVal = 1;
  const maxVal = 5;
  const range = maxVal - minVal;
  const ticks = [1, 2, 3, 4, 5];
  const [hoveredIdx, setHoveredIdx] = useState(null);

  const pathQ1 = buildDisconnectedPath(rows, 'avg_q1', pad, topHeadroom, innerH, innerW);
  const pathQ2 = buildDisconnectedPath(rows, 'avg_q2', pad, topHeadroom, innerH, innerW);

  const pointsQ1 = rows.map((r, i) => {
    const x = pad + (i * innerW) / Math.max(1, rows.length - 1);
    const v = r.avg_q1;
    const ok = v != null && v !== '' && !Number.isNaN(Number(v));
    const y = ok
      ? pad + topHeadroom + innerH - ((Number(v) - minVal) / range) * innerH
      : null;
    return { x, y, ok, v: ok ? Number(v) : null, periodStart: r.period_start };
  });
  const pointsQ2 = rows.map((r, i) => {
    const x = pad + (i * innerW) / Math.max(1, rows.length - 1);
    const v = r.avg_q2;
    const ok = v != null && v !== '' && !Number.isNaN(Number(v));
    const y = ok
      ? pad + topHeadroom + innerH - ((Number(v) - minVal) / range) * innerH
      : null;
    return { x, y, ok, v: ok ? Number(v) : null, periodStart: r.period_start };
  });

  const hovered = hoveredIdx == null ? null : {
    x: pointsQ1[hoveredIdx]?.x,
    periodStart: rows[hoveredIdx]?.period_start,
    q1: rows[hoveredIdx]?.avg_q1,
    q2: rows[hoveredIdx]?.avg_q2,
    q1c: rows[hoveredIdx]?.q1_count,
    q2c: rows[hoveredIdx]?.q2_count,
  };
  const labelEvery = rows.length > 16 ? 2 : 1;

  return (
    <div className="analytics-trends-chart-wrap analytics-feedback-chart-wrap">
      <div className="analytics-feedback-legend" aria-hidden="true">
        <span className="analytics-feedback-legend-item analytics-feedback-legend-q1">
          <span className="analytics-feedback-legend-swatch" /> {FEEDBACK_SHORT.q1}
        </span>
        <span className="analytics-feedback-legend-item analytics-feedback-legend-q2">
          <span className="analytics-feedback-legend-swatch" /> {FEEDBACK_SHORT.q2}
        </span>
      </div>
      <svg className="analytics-trends-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Session feedback averages over time">
        <line x1={pad} y1={pad} x2={pad} y2={height - pad - legendH} stroke="#c9ced6" />
        <line x1={pad} y1={height - pad - legendH} x2={width - pad} y2={height - pad - legendH} stroke="#c9ced6" />
        {ticks.map((tickVal) => {
          const t = (tickVal - minVal) / range;
          const y = pad + topHeadroom + innerH - t * innerH;
          return (
            <g key={`fb-tick-${tickVal}`}>
              <line x1={pad} y1={y} x2={width - pad} y2={y} stroke="#eef1f5" />
              <text x={6} y={y + 4} className="analytics-trends-axis-text">
                {tickVal}
              </text>
            </g>
          );
        })}
        {pathQ1 ? <path d={pathQ1} fill="none" stroke="#4f46e5" strokeWidth="2.5" /> : null}
        {pathQ2 ? <path d={pathQ2} fill="none" stroke="#059669" strokeWidth="2.5" /> : null}
        {pointsQ1.map((p, idx) => (p.ok ? (
          <circle key={`p1-${p.periodStart}`} cx={p.x} cy={p.y} r="4" fill="#4f46e5" />
        ) : null))}
        {pointsQ2.map((p, idx) => (p.ok ? (
          <circle key={`p2-${p.periodStart}`} cx={p.x} cy={p.y} r="4" fill="#059669" />
        ) : null))}
        {rows.map((_, idx) => {
          const x = pad + (idx * innerW) / Math.max(1, rows.length - 1);
          return (
            <rect
              key={`hit-${idx}`}
              x={x - 12}
              y={pad}
              width="24"
              height={innerH + topHeadroom}
              fill="transparent"
              onMouseEnter={() => setHoveredIdx(idx)}
              onMouseLeave={() => setHoveredIdx(null)}
            />
          );
        })}
        {hovered && hovered.x != null ? (
          <g>
            <rect
              x={Math.min(width - 240, hovered.x + 10)}
              y={12}
              rx="6"
              ry="6"
              width="230"
              height="64"
              fill="#111827"
              opacity="0.92"
            />
            <text x={Math.min(width - 228, hovered.x + 18)} y={28} fill="#fff" fontSize="11">
              {formatBucketLabel(hovered.periodStart, granularity)}
            </text>
            <text x={Math.min(width - 228, hovered.x + 18)} y={44} fill="#e0e7ff" fontSize="11">
              {`${FEEDBACK_SHORT.q1}: ${formatLikert(hovered.q1)} (${hovered.q1c ?? 0} n)`}
            </text>
            <text x={Math.min(width - 228, hovered.x + 18)} y={60} fill="#d1fae5" fontSize="11">
              {`${FEEDBACK_SHORT.q2}: ${formatLikert(hovered.q2)} (${hovered.q2c ?? 0} n)`}
            </text>
          </g>
        ) : null}
        {rows.map((r, idx) => (
          <text
            key={`fb-x-${r.period_start}`}
            x={pad + (idx * innerW) / Math.max(1, rows.length - 1)}
            y={height - 8}
            textAnchor="middle"
            className="analytics-trends-axis-text"
          >
            {idx % labelEvery === 0 ? formatBucketLabel(r.period_start, granularity) : ''}
          </text>
        ))}
      </svg>
    </div>
  );
}

function TrendSvg({ rows, metricKey, granularity }) {
  const width = 880;
  const height = 280;
  const pad = 36;
  const topHeadroom = 10;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2 - topHeadroom;
  const vals = rows.map((r) => Number(r[metricKey] || 0));
  const { min: minVal, max: maxVal, ticks } = buildNiceScale(vals, metricKey, 5);
  const range = Math.max(1, maxVal - minVal);
  const [hoveredIdx, setHoveredIdx] = useState(null);

  const points = rows.map((r, i) => {
    const x = pad + (i * innerW) / Math.max(1, rows.length - 1);
    const y = pad + topHeadroom + innerH - ((Number(r[metricKey] || 0) - minVal) / range) * innerH;
    return { x, y, value: Number(r[metricKey] || 0), periodStart: r.period_start };
  });
  const d = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
  const hovered = hoveredIdx == null ? null : points[hoveredIdx];
  const labelEvery = rows.length > 16 ? 2 : 1;

  return (
    <div className="analytics-trends-chart-wrap">
      <svg className="analytics-trends-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${metricKey} trend`}>
        <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#c9ced6" />
        <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#c9ced6" />
        {ticks.map((tickVal) => {
          const t = (tickVal - minVal) / range;
          const y = pad + topHeadroom + innerH - t * innerH;
          return (
            <g key={`tick-${tickVal}`}>
              <line x1={pad} y1={y} x2={width - pad} y2={y} stroke="#eef1f5" />
              <text x={6} y={y + 4} className="analytics-trends-axis-text">
                {formatMetricValue(metricKey, tickVal, { maxFractionDigits: metricKey === 'avg_chars_per_message' ? 2 : 0 })}
              </text>
            </g>
          );
        })}
        <path d={d} fill="none" stroke="#4f46e5" strokeWidth="3" />
        {points.map((p, idx) => (
          <g key={`pt-${p.periodStart}`}>
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
              x={Math.min(width - 200, hovered.x + 8)}
              y={Math.max(10, hovered.y - 36)}
              rx="6"
              ry="6"
              width="190"
              height="30"
              fill="#111827"
              opacity="0.92"
            />
            <text
              x={Math.min(width - 192, hovered.x + 16)}
              y={Math.max(29, hovered.y - 17)}
              fill="#fff"
              fontSize="12"
            >
              {`${formatBucketLabel(hovered.periodStart, granularity)}: ${formatMetricValue(metricKey, hovered.value)}`}
            </text>
          </g>
        ) : null}
        {points.map((p, idx) => (
          <text key={`x-${p.periodStart}`} x={p.x} y={height - 10} textAnchor="middle" className="analytics-trends-axis-text">
            {idx % labelEvery === 0 ? formatBucketLabel(p.periodStart, granularity) : ''}
          </text>
        ))}
      </svg>
    </div>
  );
}

function AnalyticsPanel({ open, onClose }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [overviewFetching, setOverviewFetching] = useState(false);
  const [overviewError, setOverviewError] = useState('');
  const [stats, setStats] = useState(null);
  const [granularity, setGranularity] = useState('day');
  const [periods, setPeriods] = useState(14);
  const [metricKey, setMetricKey] = useState('messages_total');
  const [trendRows, setTrendRows] = useState([]);
  const [trendsLoading, setTrendsLoading] = useState(false);
  const [trendsError, setTrendsError] = useState('');
  const [feedbackRows, setFeedbackRows] = useState([]);
  const [feedbackSummary, setFeedbackSummary] = useState(null);
  const [feedbackLoading, setFeedbackLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState('');

  const loadOverview = useCallback(async () => {
    setOverviewFetching(true);
    setOverviewError('');
    try {
      const res = await authenticatedFetch('/api/conversations/global-stats');
      const data = await res.json();
      if (!res.ok || !data?.success) {
        setOverviewError(data?.detail || 'Could not load analytics.');
        setStats(null);
        return;
      }
      setStats(data.stats || null);
    } catch {
      setOverviewError('Could not load analytics.');
      setStats(null);
    } finally {
      setOverviewFetching(false);
    }
  }, []);

  const loadTrends = useCallback(async () => {
    if (!PERIOD_OPTIONS[granularity]?.includes(periods)) {
      return;
    }
    setTrendsLoading(true);
    setTrendsError('');
    try {
      const res = await authenticatedFetch(`/api/analytics/trends?granularity=${granularity}&periods=${periods}`);
      const data = await res.json();
      if (!res.ok || !data?.success) {
        setTrendsError(data?.detail || 'Could not load trends.');
        return;
      }
      setTrendsError('');
      setTrendRows(Array.isArray(data.rows) ? data.rows : []);
    } catch {
      setTrendsError('Could not load trends.');
    } finally {
      setTrendsLoading(false);
    }
  }, [granularity, periods]);

  const loadFeedbackTrends = useCallback(async () => {
    if (!PERIOD_OPTIONS[granularity]?.includes(periods)) {
      return;
    }
    setFeedbackLoading(true);
    setFeedbackError('');
    try {
      const res = await authenticatedFetch(
        `/api/analytics/feedback-trends?granularity=${encodeURIComponent(granularity)}&periods=${periods}`
      );
      const data = await res.json();
      if (!res.ok || !data?.success) {
        setFeedbackError(data?.detail || 'Could not load feedback trends.');
        setFeedbackRows([]);
        setFeedbackSummary(null);
        return;
      }
      setFeedbackError('');
      setFeedbackRows(Array.isArray(data.rows) ? data.rows : []);
      setFeedbackSummary(data.summary || null);
    } catch {
      setFeedbackError('Could not load feedback trends.');
      setFeedbackRows([]);
      setFeedbackSummary(null);
    } finally {
      setFeedbackLoading(false);
    }
  }, [granularity, periods]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return undefined;
    let cancelled = false;
    (async () => {
      try {
        await Promise.all([loadOverview(), loadTrends()]);
      } catch {
        if (!cancelled) {
          setOverviewError((s) => s || 'Could not load analytics.');
          setTrendsError((s) => s || 'Could not load trends.');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, loadOverview, loadTrends]);

  useEffect(() => {
    if (!open || activeTab !== 'trends') return;
    loadTrends();
  }, [open, activeTab, granularity, periods, loadTrends]);

  useEffect(() => {
    if (!open || activeTab !== 'feedback') return;
    loadFeedbackTrends();
  }, [open, activeTab, granularity, periods, loadFeedbackTrends]);

  const summaryValue = useMemo(() => {
    if (!trendRows.length) return 0;
    if (metricKey === 'avg_chars_per_message') {
      const totalChars = trendRows.reduce((acc, r) => acc + Number(r.total_chars || 0), 0);
      const totalMsgs = trendRows.reduce((acc, r) => acc + Number(r.messages_total || 0), 0);
      return totalMsgs > 0 ? totalChars / totalMsgs : 0;
    }
    return trendRows.reduce((acc, r) => acc + Number(r[metricKey] || 0), 0);
  }, [trendRows, metricKey]);

  if (!open) return null;

  const periodLabel = granularity === 'day' ? 'Days' : granularity === 'week' ? 'Weeks' : 'Months';
  const firstColumnLabel = granularity === 'day' ? 'Day' : granularity === 'week' ? 'Week range' : 'Month';

  return (
    <div className="analytics-overlay" role="presentation" onClick={onClose}>
      <div
        className="analytics-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="analytics-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="analytics-header">
          <h2 id="analytics-title">Usage Analytics</h2>
          <button type="button" className="analytics-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <div className="analytics-tabs" role="tablist" aria-label="Usage analytics sections">
          <button
            type="button"
            className={`analytics-tab ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            Overview
          </button>
          <button
            type="button"
            className={`analytics-tab ${activeTab === 'trends' ? 'active' : ''}`}
            onClick={() => setActiveTab('trends')}
          >
            Trends
          </button>
          <button
            type="button"
            className={`analytics-tab ${activeTab === 'feedback' ? 'active' : ''}`}
            onClick={() => setActiveTab('feedback')}
          >
            Session feedback
          </button>
        </div>

        {activeTab === 'overview' ? (
          <div className="analytics-tab-body">
            <div className="analytics-toolbar">
              <button type="button" onClick={loadOverview} className="analytics-refresh" disabled={overviewFetching}>
                Refresh
              </button>
            </div>
            {overviewFetching ? <p className="analytics-loading">Loading…</p> : null}
            {overviewError ? <p className="analytics-error">{overviewError}</p> : null}
            {!overviewFetching && !overviewError && stats ? (
              <div className="analytics-grid">
                <div className="analytics-card"><span>Conversations</span><strong>{stats.conversation_count}</strong></div>
                <div className="analytics-card"><span>Total messages</span><strong>{stats.message_count}</strong></div>
                <div className="analytics-card"><span>Avg msgs/chat</span><strong>{stats.avg_messages_per_conversation}</strong></div>
                <div className="analytics-card"><span>Total External Function calls</span><strong>{stats.total_tool_calls}</strong></div>
                <div className="analytics-card"><span>Distinct External Functions used</span><strong>{stats.distinct_tool_count}</strong></div>
                <div className="analytics-card"><span>Avg conversation length</span><strong>{formatDuration(stats.avg_duration_seconds)}</strong></div>
                <div className="analytics-card"><span>Total chars</span><strong>{(stats.total_chars || 0).toLocaleString()}</strong></div>
                <div className="analytics-card"><span>Avg chars/msg</span><strong>{stats.avg_chars_per_message}</strong></div>
                <div className="analytics-card wide"><span>First chat</span><strong>{formatDate(stats.first_message_at)}</strong></div>
                <div className="analytics-card wide"><span>Latest chat</span><strong>{formatDate(stats.last_message_at)}</strong></div>
              </div>
            ) : null}
            {!overviewFetching && !overviewError && stats && Array.isArray(stats.top_tools) && stats.top_tools.length > 0 ? (
              <div className="analytics-top-tools">
                <h3>Top External Functions</h3>
                <ul>
                  {stats.top_tools.map((t) => (
                    <li key={t.name}>
                      <span>{getExternalFunctionLabel(t.name)}</span>
                      <strong>{t.count}</strong>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'trends' ? (
          <div className="analytics-tab-body">
            <div className="analytics-subtabs">
              {[
                { key: 'day', label: 'Daily' },
                { key: 'week', label: 'Weekly' },
                { key: 'month', label: 'Monthly' },
              ].map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  className={`analytics-subtab ${granularity === opt.key ? 'active' : ''}`}
                  onClick={() => {
                    setGranularity(opt.key);
                    setPeriods(PERIOD_OPTIONS[opt.key][0]);
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="analytics-trends-controls">
              <label>
                {periodLabel}
                <select value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
                  {PERIOD_OPTIONS[granularity].map((p) => (
                    <option key={p} value={p}>
                      Last {p}
                    </option>
                  ))}
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
              <button type="button" onClick={loadTrends} className="analytics-refresh" disabled={trendsLoading}>
                Refresh
              </button>
              {trendsLoading ? <span className="analytics-trends-updating" aria-live="polite">Updating…</span> : null}
            </div>
            {trendsError ? <p className="analytics-error">{trendsError}</p> : null}
            {trendsLoading && trendRows.length === 0 ? <p className="analytics-loading">Loading…</p> : null}
            {!trendsError && trendRows.length > 0 ? (
              <div
                className={`analytics-trends-body ${trendsLoading ? 'analytics-trends-body--refreshing' : ''}`}
                aria-busy={trendsLoading}
              >
                <div className="analytics-trends-summary">
                  <span>{METRICS.find((m) => m.key === metricKey)?.label || metricKey}</span>
                  <strong>{formatMetricValue(metricKey, summaryValue)}</strong>
                </div>
                <TrendSvg rows={trendRows} metricKey={metricKey} granularity={granularity} />
                <div className="analytics-trends-table-wrap">
                  <table className="analytics-trends-table">
                    <thead>
                      <tr>
                        <th>{firstColumnLabel}</th>
                        <th>Active sessions</th>
                        <th>Sessions started</th>
                        <th>Total msgs</th>
                        <th>User msgs</th>
                        <th>Assistant msgs</th>
                        <th>Avg chars/msg</th>
                        <th>External Function calls</th>
                      </tr>
                    </thead>
                    <tbody>
                      {trendRows.map((r) => (
                        <tr key={`${granularity}-${r.period_start}`}>
                          <td>{formatBucketLabel(r.period_start, granularity)}</td>
                          <td>{r.sessions_active}</td>
                          <td>{r.sessions_started}</td>
                          <td>{r.messages_total}</td>
                          <td>{r.messages_user}</td>
                          <td>{r.messages_assistant}</td>
                          <td>{formatMetricValue('avg_chars_per_message', r.avg_chars_per_message)}</td>
                          <td>{r.tool_calls_total}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

        {activeTab === 'feedback' ? (
          <div className="analytics-tab-body">
            <div className="analytics-subtabs">
              {[
                { key: 'day', label: 'Daily' },
                { key: 'week', label: 'Weekly' },
                { key: 'month', label: 'Monthly' },
              ].map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  className={`analytics-subtab ${granularity === opt.key ? 'active' : ''}`}
                  onClick={() => {
                    setGranularity(opt.key);
                    setPeriods(PERIOD_OPTIONS[opt.key][0]);
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
            <div className="analytics-trends-controls">
              <label>
                {periodLabel}
                <select value={periods} onChange={(e) => setPeriods(Number(e.target.value))}>
                  {PERIOD_OPTIONS[granularity].map((p) => (
                    <option key={p} value={p}>
                      Last {p}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" onClick={loadFeedbackTrends} className="analytics-refresh" disabled={feedbackLoading}>
                Refresh
              </button>
              {feedbackLoading ? <span className="analytics-trends-updating" aria-live="polite">Updating…</span> : null}
            </div>
            <p className="analytics-feedback-basis">
              Averages use session feedback (1–5). Periods are grouped by when each conversation started.
            </p>
            {feedbackError ? <p className="analytics-error">{feedbackError}</p> : null}
            {feedbackLoading && feedbackRows.length === 0 ? <p className="analytics-loading">Loading…</p> : null}
            {!feedbackError && feedbackRows.length > 0 ? (
              <div
                className={`analytics-trends-body ${feedbackLoading ? 'analytics-trends-body--refreshing' : ''}`}
                aria-busy={feedbackLoading}
              >
                <div className="analytics-feedback-summary-row">
                  <div className="analytics-card">
                    <span>{FEEDBACK_SHORT.q1}</span>
                    <strong>{formatLikert(feedbackSummary?.overall_avg_q1)}</strong>
                    <span className="analytics-feedback-n">({feedbackSummary?.total_q1 ?? 0} responses)</span>
                  </div>
                  <div className="analytics-card">
                    <span>{FEEDBACK_SHORT.q2}</span>
                    <strong>{formatLikert(feedbackSummary?.overall_avg_q2)}</strong>
                    <span className="analytics-feedback-n">({feedbackSummary?.total_q2 ?? 0} responses)</span>
                  </div>
                </div>
                {(feedbackSummary?.total_q1 ?? 0) === 0 && (feedbackSummary?.total_q2 ?? 0) === 0 ? (
                  <p className="analytics-feedback-empty">No session feedback in this date range yet.</p>
                ) : null}
                <FeedbackTrendSvg rows={feedbackRows} granularity={granularity} />
                <div className="analytics-trends-table-wrap">
                  <table className="analytics-trends-table analytics-feedback-table">
                    <thead>
                      <tr>
                        <th>{firstColumnLabel}</th>
                        <th>{FEEDBACK_SHORT.q1}</th>
                        <th>{FEEDBACK_SHORT.q2}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {feedbackRows.map((r) => (
                        <tr key={`fb-${granularity}-${r.period_start}`}>
                          <td>{formatBucketLabel(r.period_start, granularity)}</td>
                          <td>{r.q1_count > 0 ? `${formatLikert(r.avg_q1)} (${r.q1_count})` : '—'}</td>
                          <td>{r.q2_count > 0 ? `${formatLikert(r.avg_q2)} (${r.q2_count})` : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default AnalyticsPanel;
