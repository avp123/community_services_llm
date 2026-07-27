import React, { useState, useContext } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { WellnessContext } from './AppStateContextProvider';
import { API_URL } from '../config';
import '../styles/components/snap.css';
import '../styles/components/snap-login.css';

export default function SnapLogin() {
  const [searchParams] = useSearchParams();
  const mode = searchParams.get('mode') === 'simple' ? 'simple' : 'expert';
  const isApplicant = mode === 'simple';
  const next = searchParams.get('next') || (isApplicant ? '/snap/applicant' : '/snap/caseworker');

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [mfaCode, setMfaCode] = useState('');
  const [showMfaInput, setShowMfaInput] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const { setUser, setOrganization } = useContext(WellnessContext);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, mfa_code: mfaCode || undefined }),
      });

      const data = await response.json();

      if (response.status === 403 && data.detail === 'MFA code required') {
        setShowMfaInput(true);
        setError('');
        setIsLoading(false);
        return;
      }

      if (response.ok) {
        const { access_token, role, organization } = data;

        setUser({
          username,
          role,
          isAuthenticated: true,
          token: access_token,
          displayName: '',
        });
        setOrganization(organization);

        localStorage.setItem('accessToken', access_token);
        localStorage.setItem('userRole', role);
        localStorage.setItem('username', username);
        localStorage.setItem('organization', organization);
        localStorage.setItem('loginTimestamp', Date.now().toString());

        navigate(next);
      } else {
        setError(data.detail || 'Login failed. Please try again.');
        setShowMfaInput(false);
        setMfaCode('');
      }
    } catch (err) {
      setError('Server error. Please try again later.');
      console.error('SNAP login error:', err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={`snap-root ${isApplicant ? 'snap-root--applicant' : 'snap-root--caseworker'} snap-login-root`}>
      <div className="snap-login-card">
        <div className="snap-login-header">
          <div className="snap-logo-mark snap-login-mark">P</div>
          <h1 className="snap-login-title">PeerCoPilot</h1>
          <p className="snap-login-pill">Georgia SNAP · {isApplicant ? 'Applicant' : 'Caseworker'}</p>
        </div>

        {error && <div className="snap-login-error">{error}</div>}

        <form onSubmit={handleSubmit} className="snap-login-form">
          <div className="snap-login-field">
            <label htmlFor="snap-username">Username</label>
            <input
              id="snap-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={showMfaInput}
              required
            />
          </div>

          <div className="snap-login-field">
            <label htmlFor="snap-password">Password</label>
            <input
              id="snap-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={showMfaInput}
              required
            />
          </div>

          {showMfaInput && (
            <div className="snap-login-field">
              <label htmlFor="snap-mfa">Authenticator Code</label>
              <input
                id="snap-mfa"
                type="text"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                placeholder="000000"
                maxLength="6"
                required
                autoFocus
              />
              <small>Enter the 6-digit code from your authenticator app</small>
            </div>
          )}

          <button type="submit" className="snap-login-submit" disabled={isLoading}>
            {isLoading ? 'Logging in…' : 'Login'}
          </button>

          {showMfaInput && (
            <button
              type="button"
              className="snap-login-back"
              onClick={() => { setShowMfaInput(false); setMfaCode(''); }}
            >
              ← Back
            </button>
          )}
        </form>

        <p className="snap-login-register">
          Don't have an account? <Link to={`/snap/register?mode=${mode}`}>Register here</Link>
        </p>
      </div>
    </div>
  );
}
