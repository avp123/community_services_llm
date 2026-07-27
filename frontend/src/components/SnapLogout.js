import React, { useContext } from 'react';
import { useNavigate } from 'react-router-dom';
import { WellnessContext } from './AppStateContextProvider';
import { USER_DISPLAY_NAME_KEY } from '../utils/accountDisplayName';

export default function SnapLogout({ mode }) {
  const { setUser, setOrganization, resetContext } = useContext(WellnessContext);
  const navigate = useNavigate();

  const handleLogout = () => {
    setUser({ username: '', role: '', isAuthenticated: false, token: null, displayName: '' });
    setOrganization('');
    resetContext();

    localStorage.removeItem('accessToken');
    localStorage.removeItem('userRole');
    localStorage.removeItem('username');
    localStorage.removeItem('organization');
    localStorage.removeItem('loginTimestamp');
    localStorage.removeItem(USER_DISPLAY_NAME_KEY);

    navigate(`/snap/login?mode=${mode}`);
  };

  return (
    <button className="snap-mode-switch-link snap-logout-btn" onClick={handleLogout}>
      Logout
    </button>
  );
}
