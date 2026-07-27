import React, { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authenticatedFetch } from '../utils/api';
import SnapLogout from './SnapLogout';
import '../styles/components/snap.css';
import '../styles/components/snap-history.css';

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

export default function SnapHistory({ mode }) {
  const navigate = useNavigate();
  const isApplicant = mode === 'simple';
  const [conversations, setConversations] = useState(null);
  const [analytics, setAnalytics] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [convRes, statsRes] = await Promise.all([
          authenticatedFetch(`/api/snap/conversations?mode=${mode}`),
          authenticatedFetch(`/api/snap/analytics?mode=${mode}`),
        ]);
        const convData = await convRes.json();
        const statsData = await statsRes.json();
        if (cancelled) return;
        if (convRes.ok) setConversations(convData.conversations || []);
        else setError(convData.detail || 'Failed to load history.');
        if (statsRes.ok) setAnalytics(statsData);
      } catch {
        if (!cancelled) setError('Failed to load history.');
      }
    })();
    return () => { cancelled = true; };
  }, [mode]);

  const handleDelete = async (e, id) => {
    e.stopPropagation();
    e.preventDefault();
    if (!window.confirm('Delete this conversation?')) return;
    const res = await authenticatedFetch(`/api/snap/conversations/${id}`, { method: 'DELETE' });
    if (res.ok) setConversations(prev => prev.filter(c => c.conversation_id !== id));
  };

  return (
    <div className={`snap-root ${isApplicant ? 'snap-root--applicant' : 'snap-root--caseworker'}`}>
      <header className="snap-header">
        <div className="snap-header-inner">
          <div className="snap-logo">
            <span className="snap-logo-mark">P</span>
            <span className="snap-logo-text">PeerCoPilot</span>
            <span className="snap-logo-pill">Georgia SNAP · {isApplicant ? 'Applicant' : 'Caseworker'}</span>
          </div>
          <div className="snap-header-right">
            <Link className="snap-mode-switch-link" to={isApplicant ? '/snap/applicant' : '/snap/caseworker'}>
              ← Back to chat
            </Link>
            <SnapLogout mode={mode} />
          </div>
        </div>
      </header>

      <main className="snap-history-main">
        <div className="snap-history-wrap">
          <h1 className="snap-history-title">Chat History</h1>

          {analytics && (
            <div className="snap-history-stats">
              <div className="snap-history-stat">
                <span className="snap-history-stat-value">{analytics.conversation_count ?? 0}</span>
                <span className="snap-history-stat-label">Conversations</span>
              </div>
              <div className="snap-history-stat">
                <span className="snap-history-stat-value">{analytics.question_count ?? 0}</span>
                <span className="snap-history-stat-label">Questions asked</span>
              </div>
              <div className="snap-history-stat">
                <span className="snap-history-stat-value">{formatDate(analytics.last_question_at)}</span>
                <span className="snap-history-stat-label">Last activity</span>
              </div>
            </div>
          )}

          {error && <div className="snap-history-error">{error}</div>}

          {conversations === null && !error && (
            <p className="snap-history-empty">Loading…</p>
          )}

          {conversations !== null && conversations.length === 0 && (
            <p className="snap-history-empty">
              No conversations yet. <Link to={isApplicant ? '/snap/applicant' : '/snap/caseworker'}>Ask a question</Link> to get started.
            </p>
          )}

          {conversations && conversations.length > 0 && (
            <ul className="snap-history-list">
              {conversations.map(c => (
                <li
                  key={c.conversation_id}
                  className="snap-history-item"
                  onClick={() => navigate(`/snap/${isApplicant ? 'applicant' : 'caseworker'}?c=${c.conversation_id}`)}
                >
                  <div className="snap-history-item-main">
                    <span className="snap-history-item-title">{c.title || 'Untitled conversation'}</span>
                    <span className="snap-history-item-meta">
                      {c.question_count} question{c.question_count === 1 ? '' : 's'} · {formatDate(c.updated_at)}
                    </span>
                  </div>
                  <button
                    className="snap-history-item-delete"
                    onClick={(e) => handleDelete(e, c.conversation_id)}
                    aria-label="Delete conversation"
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>
    </div>
  );
}
