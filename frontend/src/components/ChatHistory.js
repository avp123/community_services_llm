import React, { useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { Navigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { WellnessContext } from './AppStateContextProvider';
import { authenticatedFetch } from '../utils/api';
import { getExternalFunctionLabel } from '../utils/externalFunctionLabels';
import '../styles/components/chat.css';
import '../styles/pages/chat-history.css';

const MarkdownContent = ({ content }) => (
  <ReactMarkdown
    skipHtml={false}
    remarkPlugins={[remarkGfm]}
    rehypePlugins={[rehypeRaw]}
    components={{
      a: ({ href, children }) => (
        <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
      ),
    }}
  >
    {content}
  </ReactMarkdown>
);

function formatDuration(seconds) {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

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

function formatRelative(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const diff = Date.now() - d.getTime();
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.round(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.round(diff / 3600000)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return '';
  }
}

function formatToolSummaryForRow(row) {
  const n = row.stats_tool_calls_total;
  if (!n) return '';
  const by = row.stats_tool_calls_by_name;
  if (by && typeof by === 'object' && Object.keys(by).length > 0) {
    const names = Object.keys(by).sort((a, b) =>
      getExternalFunctionLabel(a).localeCompare(getExternalFunctionLabel(b)),
    );
    const short = names.slice(0, 3).map(getExternalFunctionLabel).join(', ');
    const more = names.length > 3 ? '…' : '';
    return `${n} external function${n === 1 ? '' : 's'} (${short}${more})`;
  }
  return `${n} external function${n === 1 ? '' : 's'}`;
}

function StatsBar({ summary, memberLabel, toolsLabel }) {
  if (!summary) return null;
  return (
    <div className="chat-history-stats" aria-label="Conversation statistics">
      <div className="chat-history-stats-inner">
        {memberLabel ? (
          <span className="chat-history-stat-pill chat-history-stat-member">{memberLabel}</span>
        ) : null}
        {toolsLabel ? (
          <span className="chat-history-stat-pill chat-history-stat-tools" title="External functions used in this chat (Chat + Explore path)">
            {toolsLabel}
          </span>
        ) : null}
        <span className="chat-history-stat-pill">{summary.message_count} messages</span>
        <span className="chat-history-stat-pill">{summary.user_message_count} · you</span>
        <span className="chat-history-stat-pill">{summary.assistant_message_count} · assistant</span>
        <span className="chat-history-stat-pill">{summary.total_chars?.toLocaleString?.() ?? summary.total_chars} chars</span>
        <span className="chat-history-stat-pill">avg {summary.avg_chars_per_message}/msg</span>
        <span className="chat-history-stat-pill">{formatDuration(summary.duration_seconds)}</span>
        <span className="chat-history-stat-pill muted">last {formatDate(summary.last_message_at)}</span>
      </div>
    </div>
  );
}

function ChatHistory() {
  const {
    user,
    conversationID,
    setConversationID,
    setConversation,
    setChatConvo,
    setGoals,
    setResources,
  } = useContext(WellnessContext);
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [selectedRow, setSelectedRow] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [messages, setMessages] = useState([]);
  const [liveSummary, setLiveSummary] = useState(null);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [actionBanner, setActionBanner] = useState('');
  const threadEndRef = useRef(null);

  const fetchSummaries = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const res = await authenticatedFetch('/api/conversations/summary?limit=100&offset=0');
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Failed to load');
        setRows([]);
        return;
      }
      setRows(data.conversations || []);
    } catch (e) {
      setError(e.message || 'Failed to load');
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchSummaries();
  }, [fetchSummaries]);

  const sortedRows = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const la = a.last_message_at || '';
      const lb = b.last_message_at || '';
      return lb.localeCompare(la);
    });
    return copy;
  }, [rows]);

  const loadConversation = async (row) => {
    const conversationId = row.conversation_id;
    setSelectedId(conversationId);
    setSelectedRow(row);
    setLiveSummary({
      message_count: row.message_count,
      user_message_count: row.user_message_count,
      assistant_message_count: row.assistant_message_count,
      total_chars: row.total_chars,
      avg_chars_per_message: row.avg_chars_per_message,
      duration_seconds: row.duration_seconds,
      first_message_at: row.first_message_at,
      last_message_at: row.last_message_at,
    });
    setDetailLoading(true);
    setDetailError('');
    setMessages([]);
    try {
      const res = await authenticatedFetch(
        `/api/conversations/${encodeURIComponent(conversationId)}`
      );
      const data = await res.json();
      if (!res.ok) {
        setDetailError(data.detail || 'Failed to load transcript');
        return;
      }
      setMessages(data.messages || []);
      if (data.summary) setLiveSummary(data.summary);
      setSelectedRow((prev) => {
        if (!prev || prev.conversation_id !== conversationId) return prev;
        return {
          ...prev,
          title: data.title !== undefined ? data.title : prev.title,
          stats_tool_calls_total:
            data.stats_tool_calls_total !== undefined && data.stats_tool_calls_total !== null
              ? data.stats_tool_calls_total
              : prev.stats_tool_calls_total,
          stats_tool_calls_by_name:
            data.stats_tool_calls_by_name !== undefined
              ? data.stats_tool_calls_by_name
              : prev.stats_tool_calls_by_name,
        };
      });
    } catch (e) {
      setDetailError(e.message || 'Failed to load');
    } finally {
      setDetailLoading(false);
    }
  };

  useEffect(() => {
    if (threadEndRef.current) {
      threadEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, selectedId]);

  const clearSelectionIfDeleted = (deletedId) => {
    setRows((prev) => prev.filter((r) => r.conversation_id !== deletedId));
    if (selectedId === deletedId) {
      setSelectedId(null);
      setSelectedRow(null);
      setMessages([]);
      setLiveSummary(null);
      setDetailError('');
    }
  };

  const confirmDeleteConversation = async () => {
    if (!selectedId || deleteBusy) return;
    const id = selectedId;
    setDeleteBusy(true);
    setActionBanner('');
    try {
      const res = await authenticatedFetch(
        `/api/conversations/${encodeURIComponent(id)}`,
        { method: 'DELETE' }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionBanner(data.detail || 'Could not delete conversation.');
        return;
      }
      setDeleteConfirmOpen(false);
      setActionBanner('Conversation deleted.');
      clearSelectionIfDeleted(id);
      if (conversationID === id) {
        setConversation([]);
        setChatConvo([]);
        setConversationID('');
        setGoals([]);
        setResources([]);
        window.dispatchEvent(
          new CustomEvent('peercopilot:planner-reset', {
            detail: { reason: 'conversation_deleted' },
          })
        );
      }
      setTimeout(() => setActionBanner(''), 4000);
    } catch (e) {
      setActionBanner(e.message || 'Could not delete conversation.');
    } finally {
      setDeleteBusy(false);
    }
  };

  if (user.username === '' || !user.isAuthenticated) {
    return <Navigate to="/login" />;
  }

  const memberLabel = selectedRow
    ? (selectedRow.service_user_name || selectedRow.service_user_id || 'General')
    : '';
  const toolsLabel = selectedRow ? formatToolSummaryForRow(selectedRow) : '';

  return (
    <div className="chat-history-page">
      <header className="chat-history-header">
        <div>
          <h1>Chat history</h1>
          <p className="chat-history-sub">
            Only conversations you have had while logged in as <strong>{user.username}</strong> appear here. Nothing from other accounts is shown.
          </p>
        </div>
        <button type="button" className="chat-history-refresh" onClick={fetchSummaries} disabled={loading}>
          Refresh
        </button>
      </header>

      {actionBanner ? (
        <p className="chat-history-action-banner" role="status">
          {actionBanner}
        </p>
      ) : null}

      <div className="chat-history-layout">
        <aside className="chat-history-sidebar">
          {loading && <p className="chat-history-sidebar-status">Loading…</p>}
          {error && <p className="chat-history-sidebar-error">{error}</p>}
          {!loading && !error && sortedRows.length === 0 && (
            <p className="chat-history-sidebar-empty">No saved chats yet. Complete a reply in the planner to create one.</p>
          )}
          <ul className="chat-history-list">
            {sortedRows.map((r) => {
              const memberShort = r.service_user_name || r.service_user_id || '';
              const titleText = (r.title && String(r.title).trim()) || memberShort || 'Chat';
              const showMemberInMeta = Boolean(r.title && String(r.title).trim() && memberShort);
              const toolBit = formatToolSummaryForRow(r);
              const metaParts = [
                showMemberInMeta ? memberShort : null,
                formatRelative(r.last_message_at),
                `${r.message_count} msgs`,
                toolBit || null,
              ].filter(Boolean);
              return (
                <li key={r.conversation_id}>
                  <button
                    type="button"
                    className={`chat-history-list-item ${selectedId === r.conversation_id ? 'active' : ''}`}
                    onClick={() => loadConversation(r)}
                  >
                    <span className="chat-history-list-title">{titleText}</span>
                    <span className="chat-history-list-meta">
                      {metaParts.join(' · ')}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </aside>

        <main className="chat-history-main">
          {!selectedId && (
            <div className="chat-history-placeholder">
              <p>Select a conversation on the left to read it like an active chat.</p>
            </div>
          )}

          {selectedId && (
            <>
              <div className="chat-history-detail-toolbar">
                <StatsBar summary={liveSummary} memberLabel={memberLabel} toolsLabel={toolsLabel} />
                <button
                  type="button"
                  className="chat-history-delete"
                  onClick={() => setDeleteConfirmOpen(true)}
                  disabled={detailLoading || Boolean(detailError)}
                >
                  Delete conversation
                </button>
              </div>
              {detailLoading && <p className="chat-history-loading">Loading messages…</p>}
              {detailError && <p className="chat-history-detail-error">{detailError}</p>}
              {!detailLoading && !detailError && (
                <div className="conversation-thread chat-history-thread">
                  {messages.length === 0 ? (
                    <p className="chat-history-empty-transcript">No messages stored.</p>
                  ) : (
                    messages.map((m, idx) => {
                      const isUser = m.sender === 'user';
                      const senderClass = isUser ? 'user' : 'bot';
                      return (
                        <div
                          key={`${idx}-${m.created_at || ''}`}
                          className={`message-blurb ${senderClass}`}
                        >
                          <div className="chat-history-msg-label">
                            {isUser ? 'You' : 'Assistant'}
                            {m.created_at ? ` · ${formatDate(m.created_at)}` : ''}
                          </div>
                          {isUser ? (
                            <div className="chat-history-plain-text">{m.text}</div>
                          ) : (
                            <MarkdownContent content={m.text || ''} />
                          )}
                        </div>
                      );
                    })
                  )}
                  <div ref={threadEndRef} />
                </div>
              )}
            </>
          )}
        </main>
      </div>

      {deleteConfirmOpen ? (
        <div
          className="chat-history-modal-overlay"
          role="presentation"
          onClick={() => !deleteBusy && setDeleteConfirmOpen(false)}
        >
          <div
            className="chat-history-modal"
            role="dialog"
            aria-labelledby="chat-history-delete-title"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="chat-history-delete-title">Delete this conversation?</h3>
            <p className="chat-history-modal-body">
              This permanently removes the transcript and related session data from your history. If this chat is
              open in Chat + Explore, that session will be cleared. If the assistant is still responding there, wait
              until it finishes before deleting to avoid odd behavior.
            </p>
            <div className="chat-history-modal-actions">
              <button
                type="button"
                className="chat-history-modal-cancel"
                onClick={() => setDeleteConfirmOpen(false)}
                disabled={deleteBusy}
              >
                Cancel
              </button>
              <button
                type="button"
                className="chat-history-modal-delete"
                onClick={confirmDeleteConversation}
                disabled={deleteBusy}
              >
                {deleteBusy ? 'Deleting…' : 'Delete permanently'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export default ChatHistory;
