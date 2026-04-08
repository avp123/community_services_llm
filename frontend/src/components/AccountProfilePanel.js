import React, { useCallback, useContext, useEffect, useRef, useState } from 'react';
import { authenticatedFetch } from '../utils/api';
import { WellnessContext } from './AppStateContextProvider';
import { DISPLAY_NAME_MAX_LENGTH, writeStoredDisplayName } from '../utils/accountDisplayName';
import '../styles/components/account-profile-panel.css';

function AccountProfilePanel({ open, onClose }) {
  const { setUser } = useContext(WellnessContext);
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [defaultPrompt, setDefaultPrompt] = useState('');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [profileStorage, setProfileStorage] = useState({
    display_name: true,
    system_prompt_override: true,
  });
  const [fetching, setFetching] = useState(false);
  const [saveStatus, setSaveStatus] = useState('idle');

  const serverOverrideRef = useRef(null);
  const serverDisplayNameRef = useRef('');
  const allowAutosaveRef = useRef(false);
  const displayDebounceRef = useRef(null);
  const promptDebounceRef = useRef(null);

  const persistPatch = useCallback(async (patch) => {
    setSaveStatus('saving');
    try {
      const res = await authenticatedFetch('/api/account/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      });
      const payload = await res.json();
      if (!res.ok) {
        setSaveStatus('error');
        return;
      }
      if (!payload?.success) {
        setSaveStatus('error');
        return;
      }
      if (Object.prototype.hasOwnProperty.call(patch, 'display_name')) {
        serverDisplayNameRef.current = patch.display_name ?? '';
        const dn = writeStoredDisplayName(patch.display_name);
        setUser((prev) => (prev.isAuthenticated ? { ...prev, displayName: dn } : prev));
      }
      if (Object.prototype.hasOwnProperty.call(patch, 'system_prompt_override')) {
        serverOverrideRef.current = patch.system_prompt_override;
      }
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus((s) => (s === 'saved' ? 'idle' : s)), 2000);
    } catch {
      setSaveStatus('error');
    }
  }, [setUser]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    allowAutosaveRef.current = false;
    (async () => {
      setFetching(true);
      setSaveStatus('idle');
      try {
        const res = await authenticatedFetch('/api/account/profile', { method: 'GET' });
        const data = await res.json();
        if (!cancelled && res.ok && data.success) {
          const profile = data.profile || {};
          const base = profile.default_system_prompt || '';
          const override = profile.system_prompt_override;
          setUsername(profile.username || '');
          const dn = profile.display_name || '';
          setDisplayName(dn);
          serverDisplayNameRef.current = dn;
          const storedDn = writeStoredDisplayName(dn);
          setUser((prev) => (prev.isAuthenticated ? { ...prev, displayName: storedDn } : prev));
          setDefaultPrompt(base);
          const editorPrompt =
            typeof override === 'string' && override.trim().length > 0
              ? override
              : profile.effective_system_prompt || base;
          setSystemPrompt(editorPrompt);
          serverOverrideRef.current = override ?? null;
          setProfileStorage(
            profile.profile_storage || { display_name: true, system_prompt_override: true }
          );
        }
      } catch {
        if (!cancelled) setSaveStatus('error');
      } finally {
        if (!cancelled) {
          setFetching(false);
          requestAnimationFrame(() => {
            allowAutosaveRef.current = true;
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, setUser]);

  useEffect(() => {
    if (!open || fetching || !allowAutosaveRef.current) return undefined;
    if (!profileStorage.system_prompt_override) return undefined;
    const trimmedEditor = (systemPrompt || '').trim();
    const trimmedDefault = (defaultPrompt || '').trim();
    const overrideToSave = trimmedEditor === trimmedDefault ? null : systemPrompt;
    const server = serverOverrideRef.current;
    const same =
      (overrideToSave === null && (server === null || server === undefined || String(server).trim() === '')) ||
      (overrideToSave !== null && String(server || '') === String(overrideToSave || ''));
    if (same) return undefined;

    if (promptDebounceRef.current) clearTimeout(promptDebounceRef.current);
    promptDebounceRef.current = setTimeout(() => {
      persistPatch({ system_prompt_override: overrideToSave });
    }, 1000);
    return () => {
      if (promptDebounceRef.current) clearTimeout(promptDebounceRef.current);
    };
  }, [systemPrompt, defaultPrompt, open, fetching, persistPatch, profileStorage.system_prompt_override]);

  const scheduleDisplaySave = useCallback(
    (value) => {
      if (!profileStorage.display_name) return;
      if (displayDebounceRef.current) clearTimeout(displayDebounceRef.current);
      displayDebounceRef.current = setTimeout(() => {
        const v = value.trim();
        if (v === (serverDisplayNameRef.current || '').trim()) return;
        persistPatch({ display_name: value });
      }, 500);
    },
    [persistPatch, profileStorage.display_name]
  );

  const flushDisplaySave = useCallback(
    (value) => {
      if (!profileStorage.display_name) return;
      if (displayDebounceRef.current) {
        clearTimeout(displayDebounceRef.current);
        displayDebounceRef.current = null;
      }
      const v = value.trim();
      if (v === (serverDisplayNameRef.current || '').trim()) return;
      persistPatch({ display_name: value });
    },
    [persistPatch, profileStorage.display_name]
  );


  const saveSystemPromptNow = useCallback(() => {
    if (!profileStorage.system_prompt_override) return;
    if (promptDebounceRef.current) {
      clearTimeout(promptDebounceRef.current);
      promptDebounceRef.current = null;
    }
    const trimmedEditor = (systemPrompt || '').trim();
    const trimmedDefault = (defaultPrompt || '').trim();
    const overrideToSave = trimmedEditor === trimmedDefault ? null : systemPrompt;
    const server = serverOverrideRef.current;
    const same =
      (overrideToSave === null
        && (server === null || server === undefined || String(server).trim() === ''))
      || (overrideToSave !== null && String(server || '') === String(overrideToSave || ''));
    if (same) {
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus((state) => (state === 'saved' ? 'idle' : state)), 1200);
      return;
    }
    persistPatch({ system_prompt_override: overrideToSave });
  }, [defaultPrompt, persistPatch, profileStorage.system_prompt_override, systemPrompt]);

  useEffect(
    () => () => {
      if (displayDebounceRef.current) clearTimeout(displayDebounceRef.current);
      if (promptDebounceRef.current) clearTimeout(promptDebounceRef.current);
    },
    []
  );

  const reachedDisplayNameMax = displayName.length >= DISPLAY_NAME_MAX_LENGTH;

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
          <h2 id="account-profile-title">My Profile</h2>
          <div className="account-profile-header-right">
            {saveStatus === 'saving' ? (
              <span className="account-profile-autosave" aria-live="polite">
                Saving…
              </span>
            ) : null}
            {saveStatus === 'saved' ? (
              <span className="account-profile-autosave account-profile-autosave--ok" aria-live="polite">
                Saved
              </span>
            ) : null}
            {saveStatus === 'error' ? (
              <span className="account-profile-autosave account-profile-autosave--err" aria-live="polite">
                Save failed
              </span>
            ) : null}
            <button type="button" className="account-profile-close" onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
        </div>
        {fetching ? (
          <p className="account-profile-loading">Loading…</p>
        ) : (
          <div className="account-profile-form">
            <section className="account-profile-section">
              <h3>Account</h3>
              <p className="account-profile-hint">
                Your username is fixed. Display name is optional and saves automatically (max 15 chars).
              </p>
              <div className="account-profile-field">
                <label htmlFor="account-profile-username">Username</label>
                <input id="account-profile-username" type="text" value={username} disabled />
              </div>
              <div className="account-profile-field">
                <label htmlFor="account-profile-display-name">Display name (optional)</label>
                <input
                  id="account-profile-display-name"
                  type="text"
                  value={displayName}
                  maxLength={DISPLAY_NAME_MAX_LENGTH}
                  onChange={(e) => {
                    const v = e.target.value;
                    setDisplayName(v);
                    scheduleDisplaySave(v);
                  }}
                  onBlur={(e) => flushDisplaySave(e.target.value)}
                  placeholder="Enter your preferred name"
                  disabled={!profileStorage.display_name}
                />
                {profileStorage.display_name && reachedDisplayNameMax ? (
                  <p className="account-profile-inline-note" role="status" aria-live="polite">
                    15 character maximum reached.
                  </p>
                ) : null}
                {!profileStorage.display_name ? (
                  <p className="account-profile-note">
                    This server&apos;s database has not been updated with profile columns yet (one-time admin
                    step). Until migration <code>004_users_profile_prompt_override.sql</code> is applied to the
                    app database, display name cannot be saved. Refresh this page after the migration.
                  </p>
                ) : null}
              </div>
            </section>

            <section className="account-profile-section">
              <h3>System prompt</h3>
              <div className="account-profile-prompt-intro">
                <p className="account-profile-hint account-profile-hint--lead">
                  The system prompt is the standing instructions PeerCoPilot follows in <strong>every</strong> chat
                  you start while logged in. It sets tone, safety expectations, and how the assistant should support
                  you as a peer provider—without replacing your judgment or your relationship with the people you
                  support.
                </p>
                <p className="account-profile-hint">
                  <strong>You don&apos;t need to change anything</strong> to use PeerCoPilot—the default works for
                  most people.
                </p>
                <ul className="account-profile-hint-list">
                  <li>
                    <strong>Default</strong> — Standard CSPNJ-aligned behavior. Leave the text as-is unless you want
                    something different.
                  </li>
                  <li>
                    <strong>Edit</strong> — Tweak tone or boundaries for your own style. Changes apply to all your
                    chats and <strong>save automatically</strong> after you pause typing.
                  </li>
                  <li>
                    <strong>Reset</strong> — Restores the org&apos;s current default and removes your saved override.
                  </li>
                </ul>
              </div>
              {!profileStorage.system_prompt_override ? (
                <p className="account-profile-note">
                  Same as above: apply <code>004_users_profile_prompt_override.sql</code> to the app database,
                  then refresh. Until then, the full prompt editor stays read-only.
                </p>
              ) : null}
              <label htmlFor="account-profile-prompt">Full system prompt</label>
              <textarea
                id="account-profile-prompt"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={14}
                disabled={!profileStorage.system_prompt_override}
              />
              <div className="account-profile-actions">
                <button
                  type="button"
                  className="account-profile-save"
                  onClick={saveSystemPromptNow}
                  disabled={!profileStorage.system_prompt_override || saveStatus === 'saving'}
                >
                  Save
                </button>
                <button
                  type="button"
                  className="account-profile-cancel"
                  onClick={() => {
                    setSystemPrompt(defaultPrompt);
                    setSaveStatus('idle');
                    if (profileStorage.system_prompt_override) {
                      if (promptDebounceRef.current) clearTimeout(promptDebounceRef.current);
                      persistPatch({ system_prompt_override: null });
                    }
                  }}
                  disabled={!profileStorage.system_prompt_override}
                >
                  Reset to default
                </button>
              </div>
            </section>
            <div className="account-profile-actions">
              <button type="button" className="account-profile-cancel" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default AccountProfilePanel;
