import React, { useEffect, useState } from 'react';
import { authenticatedFetch } from '../utils/api';
import '../styles/components/account-profile-panel.css';

/** Modal: account-level custom prompt (all chats). */
function AccountProfilePanel({ open, onClose }) {
  const [customPrompt, setCustomPrompt] = useState('');
  const [loading, setLoading] = useState(false);
  const [fetching, setFetching] = useState(false);
  const [message, setMessage] = useState('');

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    (async () => {
      setFetching(true);
      setMessage('');
      try {
        const res = await authenticatedFetch('/api/account-prompt', { method: 'GET' });
        const data = await res.json();
        if (!cancelled && res.ok && data.success) {
          setCustomPrompt(data.custom_prompt || '');
        } else if (!cancelled) {
          setMessage('Could not load your settings.');
        }
      } catch {
        if (!cancelled) setMessage('Could not load your settings.');
      } finally {
        if (!cancelled) setFetching(false);
      }
    })();
    return () => { cancelled = true; };
  }, [open]);

  const handleSave = async (e) => {
    e.preventDefault();
    setLoading(true);
    setMessage('');
    try {
      const res = await authenticatedFetch('/api/account-prompt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ custom_prompt: customPrompt }),
      });
      const data = await res.json();
      if (!res.ok) {
        setMessage(typeof data.detail === 'string' ? data.detail : 'Save failed.');
      } else {
        setMessage('Saved.');
        setTimeout(() => setMessage(''), 2500);
      }
    } catch {
      setMessage('Save failed.');
    } finally {
      setLoading(false);
    }
  };

  if (!open) return null;

  return (
    <div className="account-profile-overlay" role="presentation" onClick={onClose}>
      <div
        className="account-profile-dialog"
        role="dialog"
        aria-labelledby="account-profile-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="account-profile-header">
          <h2 id="account-profile-title">Profile</h2>
          <button type="button" className="account-profile-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="account-profile-hint">
          Optional instructions for PeerCoPilot (tone, style, preferences). These apply to every chat for your account.
        </p>
        {fetching ? (
          <p className="account-profile-loading">Loading…</p>
        ) : (
          <form onSubmit={handleSave} className="account-profile-form">
            <label htmlFor="account-profile-prompt">Account custom prompt</label>
            <textarea
              id="account-profile-prompt"
              value={customPrompt}
              onChange={(e) => setCustomPrompt(e.target.value)}
              placeholder="e.g. Keep answers short and warm; prefer plain language."
              rows={8}
            />
            <div className="account-profile-actions">
              <button type="submit" className="account-profile-save" disabled={loading}>
                {loading ? 'Saving…' : 'Save'}
              </button>
              <button type="button" className="account-profile-cancel" onClick={onClose}>
                Close
              </button>
            </div>
            {message && (
              <p className={`account-profile-message ${message === 'Saved.' ? 'success' : 'error'}`}>
                {message}
              </p>
            )}
          </form>
        )}
      </div>
    </div>
  );
}

export default AccountProfilePanel;
