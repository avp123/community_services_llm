// GenericChat.js
import React, { useRef, useContext, useEffect, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { jsPDF } from 'jspdf';
import io from 'socket.io-client';
import '../styles/components/chat.css';
import { WellnessContext } from './AppStateContextProvider';
import { apiGet } from '../utils/api';
import { API_URL } from '../config';
import { authenticatedFetch } from '../utils/api';

const SOCKET_CONFIG = {
  transports: ['polling', 'websocket'],
  reconnectionAttempts: 5,
  timeout: 20000,
};

const PDF_CONFIG = {
  orientation: 'portrait',
  unit: 'mm',
  format: 'a4',
  lineHeight: 10,
  margin: 10,
};

const SCROLL_THRESHOLD = 50;

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

const ResetWarningModal = ({ pendingServiceUser, serviceUsers, onConfirm, onCancel }) => {
  const getUserName = () => {
    if (!pendingServiceUser) return 'General Inquiry';
    return serviceUsers.find(u => u.service_user_id === pendingServiceUser)?.service_user_name;
  };
  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h3>Switch Context?</h3>
        <p>Switching to <strong>{getUserName()}</strong> will clear the current conversation.</p>
        <p>This action cannot be undone.</p>
        <div className="modal-buttons">
          <button onClick={onCancel} className="btn-cancel">Cancel</button>
          <button onClick={onConfirm} className="btn-confirm">Switch & Reset Chat</button>
        </div>
      </div>
    </div>
  );
};

function GenericChat({ context, title, socketServerUrl, showLocation, tool }) {
  const {
    inputText, setInputText,
    inputLocationText, setInputLocationText,
    conversation, setConversation,
    chatConvo, setChatConvo,
    organization,
    user,
    conversationID, setConversationID,
    selectedServiceUser, setSelectedServiceUser,  // from context — persists across tabs
    serviceUsers, setServiceUsers,                // from context — persists across tabs
  } = useContext(context);

  const inputRef = useRef(null);
  const conversationEndRef = useRef(null);

  const [socket, setSocket] = useState(null);
  const socketRef = useRef(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [autoScrollEnabled, setAutoScrollEnabled] = useState(true);
  const [showFeedback, setShowFeedback] = useState(false);
  const [goals, setGoals] = useState([]);
  const [resources, setResources] = useState([]);
  const [pendingServiceUser, setPendingServiceUser] = useState(null);
  const [showResetWarning, setShowResetWarning] = useState(false);
  const [generatingCheckIns, setGeneratingCheckIns] = useState(false);
  const [checkIns, setCheckIns] = useState([]);
  const [version, setVersion] = useState('new');

  // Keep latest values for hydrate 404 guard without putting `conversation` / `isGenerating`
  // in hydrate's useCallback deps — those would change every stream chunk and were forcing the
  // socket effect to tear down/reconnect (wiping server session_histories and breaking replies).
  const isGeneratingRef = useRef(false);
  const conversationHydrateGuardRef = useRef([]);
  isGeneratingRef.current = isGenerating;
  conversationHydrateGuardRef.current = conversation;

  useEffect(() => {
    socketRef.current = socket;
  }, [socket]);

  const performPlannerReset = useCallback(
    (reason, socketMeta = null) => {
      setConversation([]);
      setChatConvo([]);
      setConversationID('');
      setGoals([]);
      setResources([]);
      setCheckIns([]);
      setShowFeedback(false);
      const s = socketRef.current;
      if (s) {
        s.emit('reset_session', {
          reason,
          previous_service_user_id:
            socketMeta?.previous_service_user_id ?? (selectedServiceUser || 'general'),
          new_service_user_id:
            socketMeta?.new_service_user_id ?? (selectedServiceUser || 'general'),
        });
      }
    },
    [
      selectedServiceUser,
      setConversation,
      setChatConvo,
      setConversationID,
    ]
  );

  const hydrateConversationFromDb = useCallback(async ({ allowRegression = true } = {}) => {
    if (!conversationID || !user?.isAuthenticated) return;
    try {
      const res = await authenticatedFetch(
        `/api/conversations/${encodeURIComponent(conversationID)}`
      );
      if (res.status === 404) {
        // First DB write often happens after streaming; until then GET 404s. Never wipe the
        // planner UI while we're generating or still showing the assistant loading placeholder.
        const conv = conversationHydrateGuardRef.current;
        const last = conv[conv.length - 1];
        const pendingAssistant = last?.sender === 'bot' && last?.text === 'Loading...';
        if (isGeneratingRef.current || pendingAssistant) {
          return;
        }
        performPlannerReset('conversation_not_found');
        return;
      }
      const data = await res.json();
      if (!res.ok || !data?.success) return;
      const rows = Array.isArray(data.messages) ? data.messages : [];

      const hydratedConversation = rows.map((m) => ({
        sender: m.sender === 'user' ? 'user' : 'bot',
        text: m.text || '',
      }));
      const hydratedChatConvo = rows.map((m) => ({
        role: m.sender === 'user' ? 'user' : 'assistant',
        content: m.text || '',
      }));

      setConversation((prev) => {
        if (allowRegression) return hydratedConversation;
        // Guard: never replace local state with an older/shorter transcript.
        if (hydratedConversation.length < prev.length) return prev;
        return hydratedConversation;
      });
      setChatConvo((prev) => {
        if (allowRegression) return hydratedChatConvo;
        if (hydratedChatConvo.length < prev.length) return prev;
        return hydratedChatConvo;
      });
    } catch (e) {
      console.error('[GenericChat] Failed to hydrate conversation from DB:', e);
    }
  }, [conversationID, user?.isAuthenticated, setConversation, setChatConvo, performPlannerReset]);

  const hydrateConversationFromDbRef = useRef(hydrateConversationFromDb);
  hydrateConversationFromDbRef.current = hydrateConversationFromDb;

  // Fetch service users ONCE when username is available.
  // Because serviceUsers lives in context, this only actually fetches if the
  // list is empty — subsequent tab switches find the list already populated.
  useEffect(() => {
    if (!user?.username || serviceUsers.length > 0) return;
    apiGet('/service_user_list/')
      .then(data => setServiceUsers(data || []))
      .catch(console.error);
  }, [user?.username]); // eslint-disable-line react-hooks/exhaustive-deps
  // ^ intentionally omitting serviceUsers.length to avoid re-running when list updates

  // Restore from DB when returning to an existing conversation with empty local state.
  // This preserves smooth streaming during active generation (no mid-stream overwrites).
  useEffect(() => {
    if (!conversationID || isGenerating) return;
    if (conversation.length > 0) return;
    hydrateConversationFromDb({ allowRegression: false });
  }, [conversationID, isGenerating, conversation.length, hydrateConversationFromDb]);

  // If user returns from another tab/page, refresh once from DB to recover from missed socket events.
  useEffect(() => {
    if (!conversationID) return;
    const onVisibleOrFocus = () => {
      if (isGenerating) return;
      hydrateConversationFromDb({ allowRegression: false });
    };
    document.addEventListener('visibilitychange', onVisibleOrFocus);
    window.addEventListener('focus', onVisibleOrFocus);
    return () => {
      document.removeEventListener('visibilitychange', onVisibleOrFocus);
      window.removeEventListener('focus', onVisibleOrFocus);
    };
  }, [conversationID, isGenerating, hydrateConversationFromDb]);

  // Watchdog: if the last bubble is still "Loading...", reconcile in background
  // without regressing local state. This fixes missed generation_complete/update events.
  useEffect(() => {
    if (!conversationID) return;
    const last = conversation[conversation.length - 1];
    const waitingOnAssistant = last?.sender === 'bot' && last?.text === 'Loading...';
    if (!waitingOnAssistant) return;

    const intervalId = setInterval(() => {
      hydrateConversationFromDb({ allowRegression: false });
    }, 1800);

    return () => clearInterval(intervalId);
  }, [conversationID, conversation, hydrateConversationFromDb]);

  useEffect(() => {
    const onPlannerReset = (e) => {
      performPlannerReset(e.detail?.reason || 'planner_reset');
    };
    window.addEventListener('peercopilot:planner-reset', onPlannerReset);
    return () => window.removeEventListener('peercopilot:planner-reset', onPlannerReset);
  }, [performPlannerReset]);

  // Socket setup
  useEffect(() => {
    const newSocket = io(socketServerUrl, SOCKET_CONFIG);
    setSocket(newSocket);

    newSocket.on('connect', () => console.log('[Socket.io] Connected'));
    newSocket.on('conversation_id', (data) => setConversationID(data.conversation_id));
    newSocket.on('welcome', (data) => console.log('[Socket.io] Welcome:', data));

    newSocket.on('generation_update', (data) => {
      if (typeof data.chunk === 'string') {
        setConversation(prev => {
          const last = prev[prev.length - 1];
          if (last?.sender === 'bot') {
            const updated = [...prev];
            updated[updated.length - 1].text = data.chunk;
            return updated;
          }
          return [...prev, { sender: 'bot', text: data.chunk }];
        });
      }
    });

    newSocket.on('goals_update', (data) => {
      setGoals(data.goals);
      setResources(data.resources);
    });

    newSocket.on('generation_complete', () => {
      setIsGenerating(false);
      hydrateConversationFromDbRef.current({ allowRegression: false });
    });
    newSocket.on('error', (e) => console.error('[Socket.io] Error:', e));
    newSocket.on('disconnect', (r) => console.log('[Socket.io] Disconnected:', r));

    return () => newSocket.disconnect();
  }, [socketServerUrl]);

  // Fetch check-ins when selected user changes
  useEffect(() => {
    if (selectedServiceUser) {
      authenticatedFetch(`/service_user_check_ins/?service_user_id=${selectedServiceUser}`)
        .then(res => res.json())
        .then(data => setCheckIns(data))
        .catch(() => setCheckIns([]));
    } else {
      setCheckIns([]);
    }
  }, [selectedServiceUser]);

  const handleScroll = useCallback((e) => {
    const { scrollTop, clientHeight, scrollHeight } = e.target;
    setAutoScrollEnabled(scrollTop + clientHeight >= scrollHeight - SCROLL_THRESHOLD);
  }, []);

  useEffect(() => {
    if (autoScrollEnabled && conversationEndRef.current) {
      conversationEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [conversation, autoScrollEnabled]);

  const adjustTextareaHeight = useCallback((textarea) => {
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = `${textarea.scrollHeight}px`;
    }
  }, []);

  useEffect(() => { adjustTextareaHeight(inputRef.current); }, [inputText, adjustTextareaHeight]);

  const handleInputChange = useCallback((e) => {
    setInputText(e.target.value);
    adjustTextareaHeight(e.target);
  }, [setInputText, adjustTextareaHeight]);

  const handleInputChangeLocation = useCallback((e) => {
    setInputLocationText(e.target.value);
  }, [setInputLocationText]);

  const handleSubmit = useCallback(() => {
    if (!inputText.trim() || isGenerating || !socket) return;
    const messageText = inputText.trim();
    // Build history from visible thread (not chatConvo): chatConvo can lag after navigation because
    // hydrate is skipped when conversation already has bubbles. Server session is keyed by socket sid
    // and resets on reconnect, so we always send the full prior transcript for the model.
    const previous_text = conversation
      .filter((m) => !(m.sender === 'bot' && m.text === 'Loading...'))
      .map((m) => ({
        role: m.sender === 'user' ? 'user' : 'assistant',
        content: m.text || '',
      }));

    setConversation((prev) => [
      ...prev,
      { sender: 'user', text: messageText },
      { sender: 'bot', text: 'Loading...' },
    ]);
    setChatConvo([...previous_text, { role: 'user', content: messageText }]);
    setInputText('');
    setIsGenerating(true);

    console.log('[GenericChat] start_generation, service_user_id:', selectedServiceUser);
    socket.emit('start_generation', {
      text: messageText,
      previous_text,
      model: 'A',
      organization,
      tool,
      conversation_id: conversationID,
      username: user.username,
      service_user_id: selectedServiceUser || null,
      version,
    });
  }, [
    inputText,
    isGenerating,
    socket,
    conversation,
    conversationID,
    organization,
    user,
    tool,
    version,
    selectedServiceUser,
    setConversation,
    setChatConvo,
    setInputText,
  ]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  }, [handleSubmit]);

  // Service user switching
  const handleServiceUserChange = useCallback((e) => {
    const newUserId = e.target.value;
    const hasThread = conversation.some(
      (m) => !(m.sender === 'bot' && m.text === 'Loading...')
    );
    if (hasThread && selectedServiceUser !== newUserId) {
      setPendingServiceUser(newUserId);
      setShowResetWarning(true);
    } else {
      setSelectedServiceUser(newUserId);
    }
  }, [conversation, selectedServiceUser, setSelectedServiceUser]);

  const confirmServiceUserSwitch = useCallback(() => {
    performPlannerReset('service_user_switch', {
      previous_service_user_id: selectedServiceUser || 'general',
      new_service_user_id: pendingServiceUser || 'general',
    });
    setSelectedServiceUser(pendingServiceUser);
    setPendingServiceUser(null);
    setShowResetWarning(false);
  }, [performPlannerReset, pendingServiceUser, selectedServiceUser, setSelectedServiceUser]);

  const cancelServiceUserSwitch = useCallback(() => {
    setPendingServiceUser(null);
    setShowResetWarning(false);
  }, []);

  const handleNewSession = useCallback(() => {
    performPlannerReset('new_session');
  }, [performPlannerReset]);

  const exportChatToPDF = useCallback(() => {
    const doc = new jsPDF(PDF_CONFIG);
    doc.setFontSize(16);
    doc.text('Chat History', PDF_CONFIG.margin, PDF_CONFIG.margin);
    let y = 20;
    const pageHeight = doc.internal.pageSize.height;
    conversation.forEach((msg) => {
      const lines = doc.splitTextToSize(`${msg.sender === 'user' ? 'You' : 'Bot'}: ${msg.text}`, 180);
      lines.forEach((line) => {
        if (y + PDF_CONFIG.lineHeight > pageHeight - PDF_CONFIG.margin) { doc.addPage(); y = PDF_CONFIG.margin; }
        doc.text(line, PDF_CONFIG.margin, y);
        y += PDF_CONFIG.lineHeight;
      });
    });
    doc.save('Chat_History.pdf');
  }, [conversation]);

  const printSidebar = useCallback(() => {
    const sidebar = document.querySelector('.right-section');
    if (!sidebar) { alert('Nothing to print'); return; }
    const w = window.open('', '_blank', 'width=900,height=700');
    w.document.write(`<html><head><title>Print</title><style>body{font-family:Arial,sans-serif;padding:20px}</style></head><body>${sidebar.innerHTML}<script>window.onload=()=>{window.focus();window.print();setTimeout(()=>window.close(),100)}<\/script></body></html>`);
    w.document.close();
  }, []);

  const handleGenerateCheckIns = async () => {
    if (!selectedServiceUser) { alert('Please select a member first'); return; }
    if (!conversationID) { alert("Please have a conversation first, then generate check-ins."); return; }
    setGeneratingCheckIns(true);
    try {
      const response = await authenticatedFetch('/generate_check_ins/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service_user_id: selectedServiceUser, conversation_id: conversationID }),
      });
      const data = await response.json();
      if (data.success) {
        alert(`Generated ${data.check_ins.length} check-in(s) successfully!`);
        const refresh = await authenticatedFetch(`/service_user_check_ins/?service_user_id=${selectedServiceUser}`);
        setCheckIns(await refresh.json());
      } else {
        alert(data.detail || 'No check-ins could be generated from this conversation.');
      }
    } catch (e) {
      alert('Failed to generate check-ins');
    } finally {
      setGeneratingCheckIns(false);
    }
  };

  const submitted = conversation.length > 0;

  return (
    <div className="resource-recommendation-container">
      <div className="content-area">
        <div className={`left-section ${submitted ? 'submitted' : ''}`}>
          {title ? <h1 className="page-title">{title}</h1> : null}
          <div style={{ display: 'flex', gap: '10px', marginBottom: '10px', alignItems: 'center' }}>
            <select value={selectedServiceUser} onChange={handleServiceUserChange} style={{ flex: 1 }}>
              <option value="">General Inquiry (not user-specific)</option>
              <optgroup label="Members">
                {serviceUsers.map(u => (
                  <option key={u.service_user_id} value={u.service_user_id}>
                    {u.service_user_name}
                  </option>
                ))}
              </optgroup>
            </select>
            <select value={version} onChange={(e) => setVersion(e.target.value)}
              style={{ padding: '8px 12px', borderRadius: '4px', border: '1px solid #ccc', fontSize: '14px', backgroundColor: 'white', cursor: 'pointer' }}>
              <option value="new">New Version</option>
              <option value="old">Old Version</option>
              <option value="vanilla">Vanilla GPT</option>
            </select>
          </div>

          <button className="submit-button"
            style={{ width: 'auto', padding: '8px 16px', fontSize: '14px', whiteSpace: 'nowrap' }}
            onClick={handleGenerateCheckIns}
            disabled={!selectedServiceUser || generatingCheckIns}>
            {generatingCheckIns ? 'Generating...' : 'Generate Check-ins'}
          </button>

          <h2 className="instruction">What are the member&apos;s needs and goals for today&apos;s meeting?</h2>

          <div className={`conversation-thread ${submitted ? 'visible' : ''}`}
            onScroll={handleScroll} style={{ overflowY: 'auto', maxHeight: '80vh' }}>
            {conversation.map((msg, index) => (
              <div key={index} className={`message-blurb ${msg.sender}`}>
                <MarkdownContent content={msg.text} />
              </div>
            ))}
            <div ref={conversationEndRef} />
          </div>
        </div>

        <div className="right-section">
          <div className="goals-box">
            <h3>Active Goals</h3>
            <div className="scroll-area">
              {goals.length === 0 && <p className="empty-state">No active goals.</p>}
              {goals.map((item, i) => (
                <div key={i} className="card-item">
                  <div className="card-title"><strong>{item.title}</strong></div>
                  <div className="card-details">{item.details}</div>
                </div>
              ))}
            </div>
          </div>
          <div className="resources-box">
            <h3>Resources</h3>
            <div className="scroll-area">
              {resources.length === 0 && <p className="empty-state">No resources yet.</p>}
              {resources.map((item, i) => (
                <div key={i} className="card-item">
                  <div className="card-title"><strong>{item.title}</strong></div>
                  <div className="card-details">{item.details}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className={`input-section ${submitted ? 'input-bottom' : ''}`}>
        {showLocation && (
          <div className="input-box">
            <textarea className="input-bar" placeholder="Enter location (city or county)"
              value={inputLocationText} onChange={handleInputChangeLocation} rows={1} />
          </div>
        )}
        <div className="input-box">
          <textarea className="input-bar" ref={inputRef}
            placeholder={submitted ? 'Write a follow-up to update...' : "Describe the member's situation..."}
            value={inputText} onChange={handleInputChange} onKeyDown={handleKeyDown}
            rows={1} style={{ overflow: 'hidden', resize: 'none' }} />
          <button className="submit-button" onClick={handleSubmit}>➤</button>
        </div>

        {showResetWarning && (
          <ResetWarningModal
            pendingServiceUser={pendingServiceUser}
            serviceUsers={serviceUsers}
            onConfirm={confirmServiceUserSwitch}
            onCancel={cancelServiceUserSwitch}
          />
        )}

        <div className="backend-selector-div">
          <button className="submit-button" style={{ width: '60px', height: '100%', marginLeft: '20px' }}
            onClick={handleNewSession}>
            Reset Session
          </button>
          <button className="submit-button" style={{ width: '80px', height: '100%', marginLeft: '20px' }}
            onClick={() => setShowFeedback(true)} disabled={!conversationID}>
            Feedback
          </button>
          <button className="submit-button" style={{ width: '60px', height: '100%', marginLeft: '20px' }}
            onClick={exportChatToPDF}>
            Save Session History
          </button>
          <button className="submit-button" style={{ width: '100px', height: '100%', marginLeft: '20px' }}
            onClick={printSidebar} disabled={goals.length === 0 && resources.length === 0}>
            Print Sidebar
          </button>
          {tool === 'wellness' && (
            <button className="submit-button" style={{ width: '60px', height: '100%', marginLeft: '20px' }}
              onClick={() => window.open('https://www.youtube.com/watch?v=4rg1wmo2Y8w', '_blank')}>
              Tutorial
            </button>
          )}
        </div>
        <FeedbackModal
          isOpen={showFeedback}
          onClose={() => setShowFeedback(false)}
          conversationID={conversationID}
        />
      </div>
    </div>
  );
}

const SURVEY_QUESTIONS = [
  { id: 'q1', label: 'How useful was this session for your work?' },
  { id: 'q2', label: 'How easy was PeerCoPilot to use in this session?' },
  { id: 'q3', label: 'How confident do you feel using the guidance provided?' },
  { id: 'q4', label: 'How relevant were the responses/resources to your needs?' },
  { id: 'q5', label: 'How likely are you to use PeerCoPilot again? (1=never, 5=definitely)' },
];

const FeedbackModal = ({ isOpen, onClose, conversationID }) => {
  const [answers, setAnswers] = useState({});
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(false);
  const [questionSaving, setQuestionSaving] = useState({});
  const [questionError, setQuestionError] = useState({});
  const [commentSaving, setCommentSaving] = useState(false);
  const [commentSavedAt, setCommentSavedAt] = useState(null);

  const autosaveAnswer = async (questionId, value) => {
    if (!conversationID) return;
    setQuestionSaving((prev) => ({ ...prev, [questionId]: true }));
    setQuestionError((prev) => ({ ...prev, [questionId]: '' }));
    setAnswers((prev) => ({ ...prev, [questionId]: value }));
    try {
      const res = await authenticatedFetch(
        `/api/conversations/${encodeURIComponent(conversationID)}/feedback`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question_id: questionId, value }),
        }
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.detail || 'Could not save answer.');
      }
    } catch (e) {
      setQuestionError((prev) => ({ ...prev, [questionId]: e.message || 'Could not save.' }));
    } finally {
      setQuestionSaving((prev) => ({ ...prev, [questionId]: false }));
    }
  };

  const saveComment = async () => {
    if (!conversationID) return;
    setCommentSaving(true);
    try {
      const res = await authenticatedFetch(
        `/api/conversations/${encodeURIComponent(conversationID)}/feedback`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ feedback_text: comment }),
        }
      );
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data?.detail || 'Could not save comment.');
      }
      setCommentSavedAt(Date.now());
    } catch (e) {
      alert(e.message || 'Could not save comment.');
    } finally {
      setCommentSaving(false);
    }
  };

  useEffect(() => {
    if (!isOpen || !conversationID) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await authenticatedFetch(
          `/api/conversations/${encodeURIComponent(conversationID)}/feedback`
        );
        const data = await res.json();
        if (!cancelled && res.ok && data?.success) {
          const f = data.feedback || {};
          setAnswers({
            q1: f.q1 ?? null,
            q2: f.q2 ?? null,
            q3: f.q3 ?? null,
            q4: f.q4 ?? null,
            q5: f.q5 ?? null,
          });
          setComment(f.feedback_text || '');
        }
      } catch (e) {
        if (!cancelled) console.error('[FeedbackModal] preload failed', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [isOpen, conversationID]);

  if (!isOpen) return null;

  return (
    <div className="feedback-survey-overlay" role="presentation" onClick={onClose}>
      <div className="feedback-survey-dialog" role="dialog" aria-labelledby="feedback-survey-title" onClick={(e) => e.stopPropagation()}>
        <div className="feedback-survey-header">
          <h3 id="feedback-survey-title">Session Feedback</h3>
          <button type="button" className="feedback-survey-close" onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>
        <p className="feedback-survey-sub">
          Optional quick survey. Answers autosave as you click.
        </p>
        {loading ? <p className="feedback-survey-loading">Loading previous answers...</p> : null}
        {!loading && SURVEY_QUESTIONS.map((q) => (
          <div key={q.id} className="feedback-survey-question">
            <div className="feedback-survey-label">{q.label}</div>
            <div className="feedback-survey-scale">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  type="button"
                  className={`feedback-scale-btn ${answers[q.id] === v ? 'selected' : ''}`}
                  onClick={() => autosaveAnswer(q.id, v)}
                  disabled={!!questionSaving[q.id]}
                >
                  {v}
                </button>
              ))}
              <span className="feedback-survey-save">
                {questionSaving[q.id] ? 'Saving...' : (questionError[q.id] || '')}
              </span>
            </div>
          </div>
        ))}
        <div className="feedback-survey-notes-wrap">
          <label className="feedback-survey-label">
            Optional notes
          </label>
          <textarea
            className="feedback-survey-notes"
            placeholder="Any additional comments..."
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            onBlur={saveComment}
          />
          <div className="feedback-survey-save">
            {commentSaving ? 'Saving note...' : (commentSavedAt ? 'Note saved.' : 'Notes save on blur.')}
          </div>
        </div>
        <div className="feedback-survey-actions">
          <button onClick={onClose} className="btn-cancel" type="button">
            Close
          </button>
        </div>
      </div>
    </div>
  );
};

export const WellnessGoals = () => (
  <GenericChat
    context={WellnessContext}
    socketServerUrl={`${API_URL}`}
    showLocation={false}
    tool="wellness"
  />
);

export default GenericChat;