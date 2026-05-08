import React, { useRef, useEffect, useState, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeRaw from 'rehype-raw';
import remarkGfm from 'remark-gfm';
import { authenticatedFetch } from '../utils/api';
import SnapPdfPanel from './SnapPdfPanel';
import '../styles/components/snap.css';

// ── Inline citation badge with hover tooltip ────────────────────────────────

function CiteBadge({ index, source, onOpen }) {
  const [hovered, setHovered] = useState(false);

  return (
    <span className="snap-cite-wrap">
      <button
        className="snap-cite-badge"
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onClick={() => source && onOpen && onOpen(source)}
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
          {(source.quote || source.snippet) && (
            <span className="snap-cite-tooltip-quote">
              "{source.quote || source.snippet}"
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

function AnswerWithCitations({ text, sources, onOpen }) {
  const sourceMap = Object.fromEntries(sources.map(s => [s.index, s]));

  // Replace [N] with <cite data-n="N"> inline — keeps lists/paragraphs intact
  const mdText = text.replace(/\[(\d+)\]/g, (_, n) => `<cite data-n="${n}"></cite>`);

  return (
    <div className="snap-response-body">
      <ReactMarkdown
        skipHtml={false}
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw]}
        components={{
          cite: ({ node }) => {
            const n = parseInt(node.properties?.dataN ?? '0', 10);
            return <CiteBadge index={n} source={sourceMap[n]} onOpen={onOpen} />;
          },
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
          ),
        }}
      >
        {mdText}
      </ReactMarkdown>
    </div>
  );
}

// ── References panel (collapsible, minimal) ─────────────────────────────────

function ReferencesPanel({ sources, onOpen }) {
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
            <li
              key={s.index}
              className="snap-ref-item snap-ref-item--clickable"
              onClick={() => onOpen && onOpen(s)}
              title="Click to open in PDF viewer"
            >
              <span className="snap-ref-body">
                <span className="snap-ref-title">
                  §{s.section_number} {s.section_title}
                </span>
                {(s.quote || s.key_fact) && (
                  <span className="snap-ref-fact">"{s.quote || s.key_fact}"</span>
                )}
              </span>
              <span className="snap-ref-link">
                p.{s.page_start} ↗
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ── Decision support flags panel ────────────────────────────────────────────

function FlagsPanel({ flags, mode }) {
  if (!flags || flags.length === 0) return null;
  const isExpert = mode === 'expert';
  return (
    <div className={`snap-flags ${isExpert ? 'snap-flags--expert' : 'snap-flags--simple'}`}>
      <div className="snap-flags-header">
        <span className="snap-flags-icon">{isExpert ? '⚑' : '💡'}</span>
        {isExpert ? 'Items to review' : 'Also helpful to know'}
      </div>
      <ul className="snap-flags-list">
        {flags.map((f, i) => (
          <li key={i} className="snap-flag-item">{f}</li>
        ))}
      </ul>
    </div>
  );
}

// ── Follow-up questions panel (applicant mode) ───────────────────────────────

function QuestionsPanel({ questions, onAsk }) {
  if (!questions || questions.length === 0) return null;
  return (
    <div className="snap-questions">
      <div className="snap-questions-header">To check your eligibility</div>
      <div className="snap-questions-list">
        {questions.map((q, i) => (
          <button key={i} className="snap-question-item" onClick={() => onAsk(q.question)}>
            <span className="snap-question-text">{q.question}</span>
            <span className="snap-question-reason">{q.reason}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Applicant mode: plain answer + single official link ─────────────────────


function PlainAnswer({ text, resource, flags, questions, onAsk }) {
  const plain = text.replace(/\[\d+\]/g, '');
  return (
    <div className="snap-response-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{plain}</ReactMarkdown>
      {resource && (
        <a href={resource.url} target="_blank" rel="noopener noreferrer" className="snap-learn-more">
          {resource.label} ↗
        </a>
      )}
      <FlagsPanel flags={flags} mode="simple" />
      <QuestionsPanel questions={questions} onAsk={onAsk} />
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

function Message({ msg, mode, onOpen, onAsk }) {
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

  if (mode === 'simple') {
    return (
      <div className="snap-message snap-message--bot">
        <PlainAnswer
          text={msg.text}
          resource={msg.resource}
          flags={msg.flags}
          questions={msg.questions}
          onAsk={onAsk}
        />
      </div>
    );
  }

  return (
    <div className="snap-message snap-message--bot">
      <AnswerWithCitations text={msg.text} sources={msg.sources || []} onOpen={onOpen} />
      <FlagsPanel flags={msg.flags} mode="expert" />
      <ReferencesPanel sources={msg.sources || []} onOpen={onOpen} />
    </div>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────

export default function SnapChat() {
  const [inputText, setInputText] = useState('');
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [mode, setMode] = useState('expert');
  const [pdfPanel, setPdfPanel] = useState(null);

  const onAsk = useCallback((question) => {
    setInputText(question);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, []);

  const openPdf = useCallback((source) => {
    setPdfPanel({
      page: source.page_start,
      quote: source.quote || source.key_fact || null,
      section: `§${source.section_number} ${source.section_title}`,
    });
  }, []);

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
          flags: data.flags || [],
          questions: data.questions || [],
          resource: data.resource || null,
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
    <div className={`snap-root ${pdfPanel ? 'snap-root--panel-open' : ''}`}>
      <SnapPdfPanel panel={pdfPanel} onClose={() => setPdfPanel(null)} />
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
                {mode === 'simple'
                  ? <>Ask any question about applying for Georgia SNAP benefits.<br />Get plain-language answers with links to official resources.</>
                  : <>Ask any question about Georgia SNAP eligibility, benefits, or procedures.<br />Answers cite the official policy manual with links to the source page.</>
                }
              </p>
              <div className="snap-example-queries">
                {(mode === 'simple' ? [
                  'Can I get SNAP benefits?',
                  'How much could I receive each month?',
                  'What do I need to apply?',
                  'What happens if I\'m denied?',
                ] : [
                  'What is the income limit for a household of 4?',
                  'How does categorical eligibility work?',
                  'What documents are needed to verify identity?',
                  'What are the ABAWD work requirements?',
                ]).map(q => (
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
          {messages.map((msg, i) => <Message key={i} msg={msg} mode={mode} onOpen={openPdf} onAsk={onAsk} />)}
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
