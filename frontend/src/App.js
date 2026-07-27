// App.js - Main React application routes and layout with auto-logout
import React, { useContext, useCallback, useEffect } from 'react';
import { BrowserRouter as Router, Route, Routes, Navigate, useNavigate, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar';
import Home from './components/Home';
import AuditLogs from './components/AuditLogs';
import Login from './components/Login';
import {WellnessGoals} from './components/GenericChat';
import {WellnessContextProvider, WellnessContext} from './components/AppStateContextProvider.js';
import ProfileManager from './components/ProfileManager';
import OutreachCalendar from './components/OutreachCalendar';
import ChatHistory from './components/ChatHistory';
import Register from './components/Register';
import SnapChat from './components/SnapChat';
import SnapLogin from './components/SnapLogin';
import SnapRegister from './components/SnapRegister';
import SnapHistory from './components/SnapHistory';
import { useInactivityTimeout } from './utils/useInactivityTimeout';
import { API_URL } from './config';
import { USER_DISPLAY_NAME_KEY, writeStoredDisplayName } from './utils/accountDisplayName';
import './styles/variable.css';
import './styles/base/base.css';
import './styles/layouts/content-layout.css';
import './styles/components/common.css';
import './styles/components/navbar.css';
import './styles/responsive.css';

// Gates a SNAP route behind login, redirecting to the themed SNAP login (not the main /login)
function SnapAuthGate({ mode, children }) {
  const location = useLocation();
  const hasToken = !!localStorage.getItem('accessToken');
  if (!hasToken) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/snap/login?mode=${mode}&next=${next}`} replace />;
  }
  return children;
}

// Inner component that has access to Router context
function AppContent() {
  const navigate = useNavigate();
  const { user, setUser, setOrganization, resetContext } = useContext(WellnessContext);

  // Auto-logout handler
  const handleAutoLogout = useCallback(() => {
    console.log('[Auto-Logout] Session expired due to inactivity');
    
    // Clear user state
    setUser({
      username: '',
      role: '',
      isAuthenticated: false,
      token: null,
      displayName: '',
    });
    setOrganization('');
    resetContext();
    
    // Clear localStorage
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userRole');
    localStorage.removeItem('username');
    localStorage.removeItem('organization');
    localStorage.removeItem('loginTimestamp');
    localStorage.removeItem(USER_DISPLAY_NAME_KEY);
    
    // Redirect to login with message
    alert('Your session has expired due to inactivity. Please log in again.');
    navigate('/login');
  }, [navigate, setUser, setOrganization, resetContext]);

  useEffect(() => {
    if (!user?.isAuthenticated || !user?.token) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/account/profile`, {
          headers: { Authorization: `Bearer ${user.token}` },
        });
        const data = await res.json();
        if (cancelled || !res.ok || !data?.success) return;
        const dn = writeStoredDisplayName(data.profile?.display_name);
        setUser((prev) =>
          prev.token === user.token ? { ...prev, displayName: dn } : prev,
        );
      } catch {
        /* keep cached display name */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user?.isAuthenticated, user?.token, setUser]);

  // Only activate inactivity timer if user is authenticated
  useInactivityTimeout(
    user?.isAuthenticated ? handleAutoLogout : () => {}, 
    30 // 30 minutes of inactivity
  );

  const location = useLocation();
  const isSnap = location.pathname.startsWith('/snap');

  if (isSnap) {
    return (
      <Routes>
        <Route path="/snap" element={<Navigate to="/snap/caseworker" replace />} />
        <Route path="/snap/login" element={<SnapLogin />} />
        <Route path="/snap/register" element={<SnapRegister />} />
        <Route path="/snap/caseworker" element={<SnapAuthGate mode="expert"><SnapChat mode="expert" /></SnapAuthGate>} />
        <Route path="/snap/applicant" element={<SnapAuthGate mode="simple"><SnapChat mode="simple" /></SnapAuthGate>} />
        <Route path="/snap/caseworker/history" element={<SnapAuthGate mode="expert"><SnapHistory mode="expert" /></SnapAuthGate>} />
        <Route path="/snap/applicant/history" element={<SnapAuthGate mode="simple"><SnapHistory mode="simple" /></SnapAuthGate>} />
      </Routes>
    );
  }

  return (
    <div className="App">
      <a href="#main-content" className="skip-to-main">
        Skip to main content
      </a>
      <Navbar />
      <main id="main-content" className="content" tabIndex={-1}>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/wellness-goals" element={<WellnessGoals />} />
          <Route path="/profile-manager" element={<ProfileManager />} />
          <Route path="/outreach-calendar" element={<OutreachCalendar />} />
          <Route path="/chat-history" element={<ChatHistory />} />
          <Route path="/audit-logs" element={<AuditLogs />} />
        </Routes>
      </main>
    </div>
  );
}

function App() {
  return (
    <WellnessContextProvider>
      <Router>
        <AppContent />
      </Router>
    </WellnessContextProvider>
  );
}

export default App;