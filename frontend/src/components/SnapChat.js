import React, { useRef, useEffect, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { authenticatedFetch } from '../utils/api';
import '../styles/components/snap.css';

// ── Citation parsing ────────────────────────────────────────────────────────

function parseCitations(text) {
  const parts = [];
  const re = /\[(\d+)\]/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push({ type: 'text', content: text.slice(last, m.index) });
    parts.push({ type: 'cite', index: parseInt(m[1], 10) });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: 'text', content: text.slice(last) });
  return parts;
}

// ── Inline citation badge with hover tooltip ────────────────────────────────

function CiteBadge({ index, source }) {
  const [hovered, setHovered] = useState(false);

  return (
    <span className="snap-cite-wrap">
      <button
        className="snap-cite-badge"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        aria-label={source ? `Source ${index}: ${source.section_title}` : `Source ${index}`}
      >
        {index}
      </button>
      {hovered && source && (
        <span className="snap-cite-tooltip">
          <span className="snap-cite-tooltip-label">
            §{source.section_number} {source.section_title}
          </span>
          {source.key_fact && (
            <span className="snap-cite-tooltip-fact">{source.key_fact}</span>
          )}
          {(source.snippet || source.excerpt) && (
            <span className="snap-cite-tooltip-quote">
              "{(source.snippet || source.excerpt).slice(0, 220)}"
            </span>
          )}
          <a
            href={source.pdf_url}
            target="_blank"
            rel="noopener noreferrer"
            className="snap-cite-tooltip-link"
          >
            Open p.{source.page_start} →
          </a>
        </span>
      )}
    </span>
  );
}

// ── Answer with inline citation badges ─────────────────────────────────────

function AnswerWithCitations({ text, sources }) {
  const parts = parseCitations(text);
  const sourceMap = Object.fromEntries(sources.map(s => [s.index, s]));

  return (
    <div className="snap-response-body">
      {parts.map((part, i) => {
        if (part.type === 'text') {
          return (
            <ReactMarkdown
              key={i}
              skipHtml={false}
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw]}
              components={{
                p: ({ children }) => <span className="snap-md-para">{children}</span>,
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
                ),
              }}
            >
              {part.content}
            </ReactMarkdown>
          );
        }
        return (
          <CiteBadge
            key={i}
            index={part.index}
            source={sourceMap[part.index]}
          />
        );
      })}
    </div>
  );
}

// ── References panel (collapsible, minimal) ─────────────────────────────────

function ReferencesPanel({ sources }) {
  const [open, setOpen] = useState(true);
  if (!sources || sources.length === 0) return null;

  return (
    <div className="snap-refs">
      <button className="snap-refs-header" onClick={() => setOpen(o => !o)}>
        <span className="snap-refs-icon">≡</span>
        References
        <span className="snap-refs-arrow">{open ? '∧' : '∨'}</span>
      </button>
      {open && (
        <ol className="snap-refs-list">
          {sources.map(s => (
            <li key={s.index} className="snap-ref-item">
              <span className="snap-ref-body">
                <span className="snap-ref-title">
                  §{s.section_number} {s.section_title}
                </span>
                {s.key_fact && (
                  <span className="snap-ref-fact">{s.key_fact}</span>
                )}
              </span>
              <a
                href={s.pdf_url}
                target="_blank"
                rel="noopener noreferrer"
                className="snap-ref-link"
              >
                p.{s.page_start} ↗
              </a>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ── Loading dots ────────────────────────────────────────────────────────────

function LoadingDots() {
  const [dots, setDots] = useState('');
  useEffect(() => {
    const id = setInterval(() => setDots(d => d.length >= 3 ? '' : d + '.'), 500);
    return () => clearInterval(id);
  }, []);
  return <span className="snap-dots">{dots}</span>;
}

// ── Message ─────────────────────────────────────────────────────────────────

function Message({ msg }) {
  if (msg.sender === 'user') {
    return (
      <div className="snap-message snap-message--user">
        <div className="snap-user-bubble">{msg.text}</div>
      </div>
    );
  }

  if (msg.loading) {
    return (
      <div className="snap-message snap-message--bot">
        <div className="snap-synthesizing">
          <span className="snap-chevron">›</span>
          <span className="snap-synthesizing-text">Synthesizing relevant information</span>
          <LoadingDots />
        </div>
      </div>
    );
  }

  return (
    <div className="snap-message snap-message--bot">
      <AnswerWithCitations text={msg.text} sources={msg.sources || []} />
      <ReferencesPanel sources={msg.sources || []} />
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function SnapChat() {
  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState('expert');

  const inputRef = useRef(null);
  const threadRef = useRef(null);

  useEffect(() => {
    if (threadRef.current) {
      requestAnimationFrame(() => {
        if (threadRef.current) threadRef.current.scrollTop = threadRef.current.scrollHeight;
      });
    }
  }, [messages]);

  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = `${inputRef.current.scrollHeight}px`;
    }
  }, [inputText]);

  const buildHistory = useCallback((msgs) =>
    msgs
      .filter(m => !m.loading)
      .map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text })),
    []
  );

  const handleSubmit = useCallback(async () => {
    const question = inputText.trim();
    if (!question || isLoading) return;

    const history = buildHistory(messages);
    setMessages(prev => [
      ...prev,
      { sender: 'user', text: question },
      { sender: 'bot', loading: true, text: '' },
    ]);
    setInputText('');
    setIsLoading(true);

    try {
      const res = await authenticatedFetch('/api/snap/query', {
        method: 'POST',
        body: JSON.stringify({ question, conversation_history: history, mode }),
      });
      const data = await res.json();
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          sender: 'bot',
          text: data.answer || 'Sorry, no answer was returned.',
          sources: data.sources || [],
          loading: false,
        };
        return updated;
      });
    } catch {
      setMessages(prev => {
        const updated = [...prev];
        updated[updated.length - 1] = {
          sender: 'bot',
          text: 'Something went wrong. Please try again.',
          sources: [],
          loading: false,
        };
        return updated;
      });
    } finally {
      setIsLoading(false);
    }
  }, [inputText, isLoading, messages, buildHistory, mode]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSubmit(); }
  }, [handleSubmit]);

  const hasMessages = messages.length > 0;

  return (
    <div className="snap-root">
      <header className="snap-header">
        <div className="snap-header-inner">
          <div className="snap-logo">
            <span className="snap-logo-mark">P</span>
            <span className="snap-logo-text">PeerCoPilot</span>
            <span className="snap-logo-pill">Georgia SNAP</span>
          </div>
          <div className="snap-header-right">
            <div className="snap-mode-toggle">
              <button
                className={`snap-mode-btn ${mode === 'expert' ? 'snap-mode-btn--active' : ''}`}
                onClick={() => setMode('expert')}
              >
                Caseworker
              </button>
              <button
                className={`snap-mode-btn ${mode === 'simple' ? 'snap-mode-btn--active' : ''}`}
                onClick={() => setMode('simple')}
              >
                Applicant
              </button>
            </div>
            <button className="snap-new-btn" onClick={() => setMessages([])}>
              + New
            </button>
          </div>
        </div>
      </header>

      <main className="snap-main" ref={threadRef}>
        <div className="snap-thread">
          {!hasMessages && (
            <div className="snap-welcome">
              <div className="snap-welcome-logo">P</div>
              <h1 className="snap-welcome-title">Georgia SNAP Policy Assistant</h1>
              <p className="snap-welcome-sub">
                Ask any question about Georgia SNAP eligibility, benefits, or procedures.<br />
                Answers cite the official policy manual with links to the source page.
              </p>
              <div className="snap-example-queries">
                {[
                  'What is the income limit for a household of 4?',
                  'How does categorical eligibility work?',
                  'What documents are needed to verify identity?',
                  'What are the ABAWD work requirements?',
                ].map(q => (
                  <button key={q} className="snap-example-btn" onClick={() => {
                    setInputText(q);
                    inputRef.current?.focus();
                  }}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg, i) => <Message key={i} msg={msg} />)}
        </div>
      </main>

      <div className="snap-input-wrap">
        <div className="snap-input-pill">
          <textarea
            ref={inputRef}
            className="snap-input"
            placeholder={hasMessages ? 'Ask a follow-up question...' : 'Ask about Georgia SNAP policy...'}
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className={`snap-send-btn ${inputText.trim() && !isLoading ? 'snap-send-btn--active' : ''}`}
            onClick={handleSubmit}
            disabled={!inputText.trim() || isLoading}
            aria-label="Send"
          >
            ↑
          </button>
        </div>
        <p className="snap-disclaimer">
          Answers are based on the Georgia SNAP Policy Manual. Always verify with official sources.
        </p>
      </div>
    </div>
  );
}
