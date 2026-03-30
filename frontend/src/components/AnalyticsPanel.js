import React, { useEffect, useState } from 'react';
import { authenticatedFetch } from '../utils/api';
import '../styles/components/analytics-panel.css';

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

function AnalyticsPanel({ open, onClose }) {
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState('');
  const [stats, setStats] = useState(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setFetching(true);
      setError('');
      try {
        const res = await authenticatedFetch('/api/conversations/global-stats');
        const data = await res.json();
        if (cancelled) return;
        if (!res.ok || !data?.success) {
          setError(data?.detail || 'Could not load analytics.');
          setStats(null);
          return;
        }
        setStats(data.stats || null);
      } catch {
        if (!cancelled) {
          setError('Could not load analytics.');
          setStats(null);
        }
      } finally {
        if (!cancelled) setFetching(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  if (!open) return null;

  return (
    <div className="analytics-overlay" role="presentation" onClick={onClose}>
      <div
        className="analytics-dialog"
        role="dialog"
        aria-labelledby="analytics-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="analytics-header">
          <h2 id="analytics-title">Your analytics</h2>
          <button type="button" className="analytics-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        {fetching ? <p className="analytics-loading">Loading…</p> : null}
        {error ? <p className="analytics-error">{error}</p> : null}
        {!fetching && !error && stats ? (
          <div className="analytics-grid">
            <div className="analytics-card"><span>Conversations</span><strong>{stats.conversation_count}</strong></div>
            <div className="analytics-card"><span>Total messages</span><strong>{stats.message_count}</strong></div>
            <div className="analytics-card"><span>Avg msgs/chat</span><strong>{stats.avg_messages_per_conversation}</strong></div>
            <div className="analytics-card"><span>Total tool calls</span><strong>{stats.total_tool_calls}</strong></div>
            <div className="analytics-card"><span>Distinct tools used</span><strong>{stats.distinct_tool_count}</strong></div>
            <div className="analytics-card"><span>Avg conversation length</span><strong>{formatDuration(stats.avg_duration_seconds)}</strong></div>
            <div className="analytics-card"><span>Total chars</span><strong>{(stats.total_chars || 0).toLocaleString()}</strong></div>
            <div className="analytics-card"><span>Avg chars/msg</span><strong>{stats.avg_chars_per_message}</strong></div>
            <div className="analytics-card wide"><span>First chat</span><strong>{formatDate(stats.first_message_at)}</strong></div>
            <div className="analytics-card wide"><span>Latest chat</span><strong>{formatDate(stats.last_message_at)}</strong></div>
          </div>
        ) : null}
        {!fetching && !error && stats && Array.isArray(stats.top_tools) && stats.top_tools.length > 0 ? (
          <div className="analytics-top-tools">
            <h3>Top tools</h3>
            <ul>
              {stats.top_tools.map((t) => (
                <li key={t.name}>
                  <span>{t.name}</span>
                  <strong>{t.count}</strong>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export default AnalyticsPanel;
