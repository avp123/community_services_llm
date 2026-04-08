// Navbar.js - Top navigation used across the app
import React, { useState, useContext } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { ReactComponent as HomeIcon } from '../icons/navbar/home.svg';
import { ReactComponent as ChatExploreIcon } from '../icons/navbar/chat-explore.svg';
import { ReactComponent as ProfileManagerIcon } from '../icons/navbar/profile-manager.svg';
import { ReactComponent as ConnectCalendarIcon } from '../icons/navbar/connect-calendar.svg';
import { WellnessContext } from './AppStateContextProvider';
import { getUserIdentityLabel } from '../utils/accountDisplayName';
import Logout from "./Logout.js";
import AccountProfilePanel from './AccountProfilePanel';
import AnalyticsPanel from './AnalyticsPanel';


function Navbar() {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [accountProfileOpen, setAccountProfileOpen] = useState(false);
  const [analyticsOpen, setAnalyticsOpen] = useState(false);
  const { organization, user } = useContext(WellnessContext);
  
  const toggleMenu = () => {
    setMenuOpen(!menuOpen);
  };
  
  // Convert organization to uppercase for display
  const displayOrganization = organization ? organization.toUpperCase() : '';
  const navIdentity = getUserIdentityLabel(user);
  
  if (!user.isAuthenticated) {
    return (
      <nav className="navbar">
        <h1 className="navbar-title">PeerCoPilot</h1>

      </nav>
    );

  }

  return (
    <nav className="navbar">
      <h1 className="navbar-title">PeerCoPilot</h1>
      <h3 className="navbar-subtitle">{displayOrganization}</h3>
      <h3 className="navbar-subtitle">{navIdentity}</h3>
      <div className="hamburger" onClick={toggleMenu}>
        &#9776; {/* Hamburger icon */}
      </div>
      <div className={`navbar-links ${menuOpen ? 'active' : ''}`}>
        <Link
          to="/"
          className={`navbar-button ${location.pathname === '/' ? 'active' : ''}`}
        >
          <HomeIcon className="navbar-icon" aria-hidden />
          Home
        </Link>
        <div className="navbar-spacer"></div>
        <div className="navbar-label">Tool</div>
        <Link
          to="/wellness-goals"
          className={`navbar-button ${
            location.pathname === '/wellness-goals' ? 'active' : ''
          }`}
        >
          <ChatExploreIcon className="navbar-icon" aria-hidden />
          Chat + Explore
        </Link>
        <Link
          to="/profile-manager"
          className={`navbar-button ${
            location.pathname === '/profile-manager' ? 'active' : ''
          }`}
        >
          <ProfileManagerIcon className="navbar-icon" aria-hidden />
          Profile Manager
        </Link>
        <Link
          to="/outreach-calendar"
          className={`navbar-button ${
            location.pathname === '/outreach-calendar' ? 'active' : ''
          }`}
        >
          <ConnectCalendarIcon className="navbar-icon" aria-hidden />
          Connect with Members
        </Link>
        <div className="navbar-footer-actions">
          <Link
            to="/chat-history"
            className={`navbar-profile-link navbar-footer-link ${
              location.pathname === '/chat-history' ? 'active' : ''
            }`}
            onClick={() => setMenuOpen(false)}
          >
            Chat history
          </Link>
          <button
            type="button"
            className="navbar-profile-link"
            onClick={() => {
              setAnalyticsOpen(true);
              setMenuOpen(false);
            }}
          >
            Usage Analytics
          </button>
          <button
            type="button"
            className="navbar-profile-link"
            onClick={() => {
              setAccountProfileOpen(true);
              setMenuOpen(false);
            }}
          >
            My Profile
          </button>
          <Logout />
        </div>
      </div>
      <AnalyticsPanel open={analyticsOpen} onClose={() => setAnalyticsOpen(false)} />
      <AccountProfilePanel open={accountProfileOpen} onClose={() => setAccountProfileOpen(false)} />
    </nav>
  );
}

export default Navbar;