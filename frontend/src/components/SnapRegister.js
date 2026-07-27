import React, { useState, useContext } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { WellnessContext } from './AppStateContextProvider';
import { API_URL } from '../config';
import '../styles/components/snap.css';
import '../styles/components/snap-login.css';

export default function SnapRegister() {
  const [searchParams] = useSearchParams();
  const mode = searchParams.get('mode') === 'simple' ? 'simple' : 'expert';
  const isApplicant = mode === 'simple';
  const next = searchParams.get('next') || (isApplicant ? '/snap/applicant' : '/snap/caseworker');

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const navigate = useNavigate();
  const { setUser, setOrganization } = useContext(WellnessContext);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');

    if (password !== confirmPassword) {
      setError('Passwords do not match.');
      return;
    }

    setIsLoading(true);
    try {
      const response = await fetch(`${API_URL}/api/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password, organization: 'georgia' }),
      });

      const data = await response.json();

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
        setError(data.detail || 'Registration failed. Please try again.');
      }
    } catch (err) {
      console.error('SNAP registration error:', err);
      setError('Server error. Please try again later.');
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
            <label htmlFor="snap-reg-username">Username</label>
            <input
              id="snap-reg-username"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="snap-login-field">
            <label htmlFor="snap-reg-password">Password</label>
            <input
              id="snap-reg-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <div className="snap-login-field">
            <label htmlFor="snap-reg-confirm">Confirm Password</label>
            <input
              id="snap-reg-confirm"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" className="snap-login-submit" disabled={isLoading}>
            {isLoading ? 'Registering…' : 'Register'}
          </button>
        </form>

        <p className="snap-login-register">
          Already have an account? <Link to={`/snap/login?mode=${mode}`}>Login here</Link>
        </p>
      </div>
    </div>
  );
}
