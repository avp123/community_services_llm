import React, { useContext } from 'react';
import { WellnessContext } from './AppStateContextProvider';
import { useNavigate } from 'react-router-dom';
import { USER_DISPLAY_NAME_KEY } from '../utils/accountDisplayName';

function Logout() {
  const { setUser, setOrganization, resetContext } = useContext(WellnessContext);
  const navigate = useNavigate();

  const handleLogout = (reason = 'manual') => {
    console.log(`[Logout] User logged out: ${reason}`);
    
    setUser({
      username: '',
      role: '',
      isAuthenticated: false,
      token: null,
      displayName: '',
    });
    setOrganization('');
    resetContext();
    
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userRole');
    localStorage.removeItem('username');
    localStorage.removeItem('organization');
    localStorage.removeItem('loginTimestamp');
    localStorage.removeItem(USER_DISPLAY_NAME_KEY);
    
    navigate('/login');
  };

  return (
    <button onClick={() => handleLogout('manual')} className="logout-button">
      Logout
    </button>
  );
}

export { Logout };
export default Logout;
