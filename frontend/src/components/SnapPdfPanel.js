import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';

const MAX_LOOKAHEAD = 4; // pages to scan forward if highlights not found

function esc(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// Pull significant numbers out of any text (quote, key_fact, etc.).
// Numbers survive across PDF extractors; prose doesn't.
function extractTokens(text) {
  if (!text) return [];
  const nums = text.match(/[\d,]{3,}/g) || [];           // 3+ digit groups: 3,483  2680
  const significant = nums.filter(n => n.replace(/,/g, '').length >= 3);
  if (significant.length) return [...new Set(significant)];
  // No numbers — fall back to long words
  return [...new Set(text.split(/\s+/).filter(w => w.length > 5))].slice(0, 8);
}

function highlightStr(str, tokens) {
  if (!tokens.length || str.trim().length < 2) return null;
  // Strip commas/spaces from both sides for flexible matching (3,483 ↔ 3483)
  const strDigits = str.replace(/[,\s]/g, '');
  return tokens.some(t => str.includes(t) || strDigits.includes(t.replace(/,/g, '')));
}

export default function SnapPdfPanel({ panel, onClose }) {
  const [numPages, setNumPages] = useState(null);
  const [currentPage, setCurrentPage] = useState(null);
  const attemptsRef = useRef(0);
  const lockedRef = useRef(false);   // true once highlight page is found
  const foundPageRef = useRef(null); // the page number where highlights were found
  const viewerRef = useRef(null);

  const { page, quote, section } = panel || {};

  // Reset whenever a new citation is opened
  useEffect(() => {
    if (page) {
      setCurrentPage(page);
      attemptsRef.current = 0;
      lockedRef.current = false;
      foundPageRef.current = null;
    }
  }, [page, quote]);

  const tokens = useMemo(() => extractTokens(quote), [quote]);

  // Wait for the text layer to paint, then check for highlights.
  // Once locked (highlight found), this effect does nothing — manual ‹ › navigation works freely.
  useEffect(() => {
    if (!currentPage || !tokens.length || lockedRef.current) return;

    const timer = setTimeout(() => {
      const marks = viewerRef.current?.querySelectorAll('.snap-pdf-hl');
      if (marks && marks.length > 0) {
        marks[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        lockedRef.current = true;
        foundPageRef.current = currentPage;
      } else if (attemptsRef.current < MAX_LOOKAHEAD) {
        attemptsRef.current += 1;
        setCurrentPage(p => p + 1);
      }
    }, 700);

    return () => clearTimeout(timer);
  }, [currentPage, tokens]);

  const customTextRenderer = useCallback(({ str }) => {
    const s = esc(str);
    // Only highlight on the specific page where the match was found.
    // On all other pages, return plain text so browsing is clean.
    if (foundPageRef.current !== null && currentPage !== foundPageRef.current) return s;
    return highlightStr(str, tokens) ? `<mark class="snap-pdf-hl">${s}</mark>` : s;
  }, [tokens, currentPage]);

  if (!panel) return null;

  return (
    <>
      <div className="snap-pdf-backdrop" onClick={onClose} />

      <div className="snap-pdf-panel snap-pdf-panel--open">
        {/* Header */}
        <div className="snap-pdf-header">
          <div className="snap-pdf-header-info">
            <span className="snap-pdf-header-section">{section}</span>
            <span className="snap-pdf-header-page">
              p.{currentPage}
              {currentPage !== page && (
                <span className="snap-pdf-header-scanned"> (scanned from p.{page})</span>
              )}
            </span>
          </div>
          <button className="snap-pdf-close" onClick={onClose} aria-label="Close">✕</button>
        </div>

        {/* Cited-text callout */}
        {quote && (
          <div className="snap-pdf-callout">
            <span className="snap-pdf-callout-label">Cited text</span>
            <span className="snap-pdf-callout-quote">"{quote}"</span>
          </div>
        )}

        {/* PDF viewer */}
        <div className="snap-pdf-viewer" ref={viewerRef}>
          <Document
            file="/snap_manual.pdf"
            onLoadSuccess={({ numPages }) => setNumPages(numPages)}
            loading={<div className="snap-pdf-status">Loading PDF…</div>}
            error={<div className="snap-pdf-status snap-pdf-status--err">Could not load PDF.</div>}
          >
            <Page
              key={currentPage}
              pageNumber={currentPage || 1}
              width={Math.min(560, window.innerWidth * 0.92)}
              customTextRenderer={customTextRenderer}
              renderAnnotationLayer={false}
            />
          </Document>
        </div>

        {/* Footer */}
        <div className="snap-pdf-footer">
          <div className="snap-pdf-footer-nav">
            <button
              className="snap-pdf-nav-btn"
              onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
              disabled={currentPage <= 1}
            >‹</button>
            <span className="snap-pdf-footer-pages">
              {numPages ? `${currentPage} / ${numPages}` : `p.${currentPage}`}
            </span>
            <button
              className="snap-pdf-nav-btn"
              onClick={() => setCurrentPage(p => Math.min(numPages || p, p + 1))}
              disabled={currentPage >= numPages}
            >›</button>
          </div>
          <a
            href={`/snap_manual.pdf#page=${currentPage}`}
            target="_blank"
            rel="noopener noreferrer"
            className="snap-pdf-footer-link"
          >
            Open full PDF ↗
          </a>
        </div>
      </div>
    </>
  );
}
