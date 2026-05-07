import React, { useRef, useEffect, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import io from 'socket.io-client';
import { API_URL } from '../config';
import '../styles/components/snap.css';

const SOCKET_CONFIG = {
  transports: ['polling', 'websocket'],
  reconnectionAttempts: 5,
  timeout: 20000,
};

const LoadingDots = () => {
  const [dots, setDots] = useState('');
  useEffect(() => {
    const id = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 500);
    return () => clearInterval(id);
  }, []);
  return <span className="snap-dots">{dots}</span>;
};

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

export default function SnapChat() {
  const token = localStorage.getItem('accessToken');
  const username = localStorage.getItem('username');
  const organization = localStorage.getItem('organization') || 'cspnj';

  const [inputText, setInputText] = useState('');
  const [conversation, setConversation] = useState([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [conversationID, setConversationID] = useState('');
  const [socket, setSocket] = useState(null);
  const [autoScroll, setAutoScroll] = useState(true);

  const inputRef = useRef(null);
  const threadRef = useRef(null);
  const socketRef = useRef(null);
  const isGeneratingRef = useRef(false);
  isGeneratingRef.current = isGenerating;

  useEffect(() => { socketRef.current = socket; }, [socket]);

  // Socket setup
  useEffect(() => {
    const s = io(API_URL, SOCKET_CONFIG);
    setSocket(s);

    s.on('connect', () => console.log('[Snap] Socket connected'));
    s.on('conversation_id', (data) => setConversationID(data.conversation_id));

    s.on('generation_update', (data) => {
      if (typeof data.chunk !== 'string') return;
      setConversation(prev => {
        const last = prev[prev.length - 1];
        if (last?.sender === 'bot') {
          const updated = [...prev];
          updated[updated.length - 1] = { ...last, text: data.chunk };
          return updated;
        }
        return [...prev, { sender: 'bot', text: data.chunk }];
      });
    });

    s.on('generation_complete', () => setIsGenerating(false));
    s.on('disconnect', (r) => console.log('[Snap] Disconnected:', r));

    return () => s.disconnect();
  }, []);

  // Auto-scroll
  useEffect(() => {
    if (!autoScroll || !threadRef.current) return;
    requestAnimationFrame(() => {
      if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
    });
  }, [conversation, autoScroll]);

  const handleScroll = useCallback((e) => {
    const { scrollTop, clientHeight, scrollHeight } = e.target;
    setAutoScroll(scrollTop + clientHeight >= scrollHeight - 60);
  }, []);

  const handleSubmit = useCallback(() => {
    const s = socketRef.current;
    if (!inputText.trim() || isGeneratingRef.current || !s) return;
    const messageText = inputText.trim();

    const previous_text = conversation
      .filter(m => !(m.sender === 'bot' && m.text === 'Loading...'))
      .map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text || '' }));

    setAutoScroll(true);
    setConversation(prev => [
      ...prev,
      { sender: 'user', text: messageText },
      { sender: 'bot', text: 'Loading...' },
    ]);
    setInputText('');
    setIsGenerating(true);

    s.emit('start_generation', {
      text: messageText,
      previous_text,
      model: 'A',
      organization,
      conversation_id: conversationID,
      username,
      service_user_id: null,
      version: 'new',
    });
  }, [inputText, conversation, conversationID, organization, username]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  }, [handleSubmit]);

  const handleNewSession = useCallback(() => {
    setConversation([]);
    setConversationID('');
    setIsGenerating(false);
    const s = socketRef.current;
    if (s) s.emit('reset_session', { reason: 'new_session' });
  }, []);

  const hasMessages = conversation.length > 0;

  return (
    <div className="snap-root">
      {/* Header */}
      <header className="snap-header">
        <div className="snap-header-inner">
          <div className="snap-logo">
            <span className="snap-logo-mark">P</span>
            <span className="snap-logo-text">PeerCoPilot</span>
          </div>
          <button className="snap-new-btn" onClick={handleNewSession}>
            + New Session
          </button>
        </div>
      </header>

      {/* Main content */}
      <main
        className={`snap-main ${hasMessages ? 'snap-main--has-messages' : ''}`}
        ref={threadRef}
        onScroll={handleScroll}
      >
        <div className="snap-thread">
          {!hasMessages && (
            <div className="snap-welcome">
              <div className="snap-welcome-logo">P</div>
              <h1 className="snap-welcome-title">How can I help you today?</h1>
              <p className="snap-welcome-sub">Ask about resources, benefits, or peer support.</p>
            </div>
          )}

          {conversation.map((msg, i) => (
            <div key={i} className={`snap-message snap-message--${msg.sender}`}>
              {msg.sender === 'user' ? (
                <div className="snap-user-bubble">{msg.text}</div>
              ) : (
                <div className="snap-bot-message">
                  {msg.text === 'Loading...' ? (
                    <div className="snap-synthesizing">
                      <span className="snap-chevron">›</span>
                      <span className="snap-synthesizing-text">Thinking</span>
                      <LoadingDots />
                    </div>
                  ) : (
                    <div className="snap-response-body">
                      <MarkdownContent content={msg.text} />
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      </main>

      {/* Bottom input */}
      <div className="snap-input-wrap">
        <div className="snap-input-pill">
          <textarea
            ref={inputRef}
            className="snap-input"
            placeholder={hasMessages ? 'Ask a follow-up question...' : 'Describe the situation or ask a question...'}
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className={`snap-send-btn ${inputText.trim() && !isGenerating ? 'snap-send-btn--active' : ''}`}
            onClick={handleSubmit}
            disabled={!inputText.trim() || isGenerating}
            aria-label="Send"
          >
            ↑
          </button>
        </div>
        <p className="snap-disclaimer">PeerCoPilot may make mistakes. Verify important information.</p>
      </div>
    </div>
  );
}
