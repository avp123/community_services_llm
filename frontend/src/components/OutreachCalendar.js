// OutreachCalendar.js
import React, { useEffect, useState, useContext, useCallback, useMemo } from 'react';
import Sidebar from './Sidebar';
import SidebarInformation from './SidebarInformation';
import { WellnessContext } from './AppStateContextProvider';
import { useCheckIns } from '../hooks/useCheckIns';
import { apiGet } from '../utils/api';
import { statusConfig } from '../utils/colorUtils';
import { StatusLegend } from './ProfileManager';
import '../styles/pages/calendar.css';

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'
];
const DAYS_OF_WEEK = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

const parseCheckInDate = (s) => {
  if (!s) return null;
  const parts = s.split('-').map(Number);
  if (parts[0] > 31) return new Date(parts[0], parts[1] - 1, parts[2]);
  return new Date(parts[2], parts[0] - 1, parts[1]);
};

const getDateKey = (d) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;

const OutreachCalendar = () => {
  const { user } = useContext(WellnessContext);

  const [search, setSearch] = useState('');
  const [allOutreach, setAllOutreach] = useState([]);
  const [currentPatient, setCurrentPatient] = useState(null);
  const [hasSidebar, setSidebar] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [completingId, setCompletingId] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { checkIns, fetchCheckIns, saveAllCheckIns, updatePatientLastSession } = useCheckIns();

  useEffect(() => {
    if (currentPatient?.service_user_id) fetchCheckIns(currentPatient.service_user_id);
  }, [currentPatient?.service_user_id, fetchCheckIns]);

  const fetchOutreach = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await apiGet('/outreach_list/');
      console.log('[Calendar] Sample item:', data[0]);
      setAllOutreach(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { fetchOutreach(); }, [fetchOutreach]);

  const outreachByDate = useMemo(() => {
    const grouped = {};
    allOutreach.forEach((item) => {
      const date = parseCheckInDate(item.check_in);
      if (!date || isNaN(date.getTime())) return;
      const key = getDateKey(date);
      if (!grouped[key]) grouped[key] = { date, outreach: [] };
      grouped[key].outreach.push({ ...item, cfg: statusConfig(item.status) });
    });
    return grouped;
  }, [allOutreach]);

  const handleCompleteCheckIn = useCallback(async (checkInId, e) => {
    e.stopPropagation();
    if (checkInId == null) {
      alert('Cannot complete: missing check-in ID. Try refreshing.');
      return;
    }
    console.log('[Calendar] Completing check_in_id:', checkInId, typeof checkInId);
    if (!window.confirm('Mark this check-in as complete and remove it from the calendar?')) return;
    setCompletingId(checkInId);
    try {
      await saveAllCheckIns({}, null, [checkInId], []);
      await fetchOutreach();
    } catch (err) {
      alert(`Failed to complete check-in: ${err.message}`);
    } finally {
      setCompletingId(null);
    }
  }, [saveAllCheckIns, fetchOutreach]);

  const handlePatientClick = useCallback((patient) => {
    setCurrentPatient(patient);
    setSidebar(true);
  }, []);

  const handleCloseSidebar = useCallback(() => {
    setSidebar(false);
    setCurrentPatient(null);
  }, []);

  const handleUpdatePatient = async (updatedData) => {
    setIsSubmitting(true);
    try {
      if (updatedData.last_session !== undefined) {
        await updatePatientLastSession(currentPatient.service_user_id, updatedData.last_session);
        setCurrentPatient(prev => ({ ...prev, ...updatedData }));
      }
      await fetchOutreach();
      alert('Profile saved successfully!');
    } catch (err) {
      alert(`Failed to update: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveAllCheckIns = async (allEdits, deletions, additions) => {
    setIsSubmitting(true);
    try {
      await saveAllCheckIns(allEdits, currentPatient.service_user_id, deletions, additions);
      await fetchOutreach();
      alert('All changes saved successfully!');
    } catch (err) {
      alert(`Failed to update check-ins: ${err.message}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const dateComponents = useMemo(() => {
    const sorted = Object.keys(outreachByDate).sort(
      (a, b) => outreachByDate[a].date.getTime() - outreachByDate[b].date.getTime()
    );
    const q = search.toLowerCase();

    return sorted.map((key) => {
      const { date, outreach } = outreachByDate[key];
      const filtered = outreach.filter(item =>
        (item.name || item.service_user_name || '').toLowerCase().includes(q)
      );
      if (filtered.length === 0 && search) return null;

      return (
        <div key={key} className="day">
          <div className="date black">{date.getDate()}</div>
          <div className="info">
            {DAYS_OF_WEEK[date.getDay()]}, {MONTHS[date.getMonth()]} {date.getDate()}, {date.getFullYear()}
          </div>
          <ul>
            {filtered.map((item, idx) => {
              const checkInId = item.check_in_id;
              const isCompleting = completingId === checkInId;
              const { color, bg, symbol } = item.cfg;

              return (
                <li className="calendar-item-row" key={`${item.service_user_id}-${item.check_in}-${idx}`}
                  style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
                  <span
                    className="calendar-item-content"
                    style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', flex: 1 }}
                    onClick={() => handlePatientClick(item)}
                  >
                    {/* Symbol + color dot — both cues for colorblind users */}
                    <span aria-hidden="true" style={{
                      width: '18px', height: '18px', borderRadius: '50%',
                      background: bg, color, fontSize: '11px', fontWeight: 700,
                      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                      border: `1.5px solid ${color}`, flexShrink: 0,
                    }}>
                      {symbol}
                    </span>
                    Follow-up Wellness Check-in w/ {item.name || item.service_user_name}
                  </span>

                  <button
                    className="calendar-item-action"
                    onClick={(e) => handleCompleteCheckIn(checkInId, e)}
                    disabled={isCompleting || checkInId == null}
                    title={checkInId == null ? 'No check-in ID — refresh page' : 'Mark complete & remove'}
                    style={{
                      fontSize: '11px', padding: '2px 8px', borderRadius: '4px',
                      border: '1px solid #2563EB', background: '#EFF6FF', color: '#2563EB',
                      cursor: checkInId == null ? 'not-allowed' : 'pointer',
                      opacity: checkInId == null ? 0.5 : 1,
                      whiteSpace: 'nowrap', flexShrink: 0,
                    }}
                  >
                    {isCompleting ? '...' : '✓ Complete Check-In'}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      );
    }).filter(Boolean);
  }, [outreachByDate, search, completingId, handleCompleteCheckIn, handlePatientClick]);

  return (
    <div className="container">
      <div className={`main-content ${hasSidebar ? 'shifted' : ''}`}>
        <div className="header">
          <h2 style={{ paddingRight: '20px' }}>
            {MONTHS[new Date().getMonth()]} {new Date().getFullYear()}
          </h2>
          <StatusLegend />
          <input type="text" placeholder="Search by member name..." className="search-box"
            value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search members" />
        </div>

        <div className="table-wrapper">
          <div className="schedule">
            {isLoading && <div className="loading-message">Loading outreach data...</div>}
            {error && <div className="error-message">Error: {error} <button onClick={fetchOutreach}>Retry</button></div>}
            {!isLoading && !error && dateComponents.length === 0 && (
              <div className="empty-message">{search ? `No results for "${search}"` : 'No outreach scheduled'}</div>
            )}
            {!isLoading && !error && dateComponents}
          </div>
        </div>
      </div>

      <Sidebar isOpen={hasSidebar} content={
        hasSidebar && currentPatient ? (
          <SidebarInformation
            checkIns={checkIns} patient={currentPatient}
            isEditable={false} isSubmitting={isSubmitting}
            onSubmit={() => {}} onUpdatePatient={handleUpdatePatient}
            onSaveAllCheckIns={handleSaveAllCheckIns} onClose={handleCloseSidebar}
          />
        ) : null
      } />
    </div>
  );
};

export default OutreachCalendar;