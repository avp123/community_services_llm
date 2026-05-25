import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/TextLayer.css';
import 'react-pdf/dist/Page/AnnotationLayer.css';

pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';

const MAX_LOOKAHEAD = 4;

function esc(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function norm(text) {
  return text.toLowerCase().replace(/[^a-z0-9\s]/g, ' ').replace(/\s+/g, ' ').trim();
}

// Returns the set of item indices from `items` (PDF.js TextContent.items) that
// fall within a match of `text` in the concatenated page text.
//
// Design:
//   1. Build fullText from non-empty items only — bullets ("•" → "") create
//      double spaces that break indexOf.
//   2. Only search the portion BEFORE the first "…". Everything after "…" tends
//      to be a short generic continuation ("individuals who are applying…") that
//      matches the wrong place on the page. The first portion is always long and
//      specific enough to locate the right passage.
//   3. No bridging between multiple fragments — bridging was causing large
//      false-positive ranges when the two matches landed far apart.
function findMatchedIndices(items, text) {
  if (!text || !items.length) return new Set();

  // Numeric shortcut: only for comma-formatted numbers like $3,483 or 1,394/month.
  // Plain digits (section refs "3320", law refs "308") must NOT trigger this path —
  // they appear throughout the document and produce false-positive highlights.
  const nums = (text.match(/\d[\d,]*\d/g) || [])
    .filter(n => n.includes(',') && n.replace(/,/g, '').length >= 3);
  if (nums.length) {
    const matched = new Set();
    items.forEach((item, idx) => {
      const digits = item.str.replace(/[,\s]/g, '');
      if (nums.some(t => item.str.includes(t) || digits.includes(t.replace(/,/g, '')))) {
        matched.add(idx);
      }
    });
    return matched;
  }

  // Build fullText from non-empty items, tracking each item's [start, end).
  const ranges = [];
  let fullText = '';
  for (let i = 0; i < items.length; i++) {
    const normed = norm(items[i].str);
    if (!normed) continue;
    if (fullText) fullText += ' ';
    const start = fullText.length;
    fullText += normed;
    ranges.push({ idx: i, start, end: fullText.length });
  }

  // Strip editorial brackets ([and], [note] etc.), then take only the first
  // segment before any "…". That segment is the longest, most specific part.
  const stripped = text.replace(/\[[^\]]*\]/g, '');
  const firstPart = stripped.split(/…|\.{3,}/)[0];
  // Cap at 400 chars so toSearch always fits within a single page's text length.
  const toSearch = norm(firstPart.length >= 30 ? firstPart : stripped).slice(0, 400);

  // eslint-disable-next-line no-console
  console.log('[SNAP-HL] toSearch (first 120):', toSearch.slice(0, 120), '  len:', toSearch.length);

  if (toSearch.length < 20) return new Set();

  const matchStart = fullText.indexOf(toSearch);
  // eslint-disable-next-line no-console
  console.log('[SNAP-HL] matchStart:', matchStart, '  fullText length:', fullText.length);
  // eslint-disable-next-line no-console
  if (matchStart !== -1) console.log('[SNAP-HL] fullText around match:', fullText.slice(Math.max(0, matchStart - 20), matchStart + 80));

  if (matchStart === -1) return new Set();
  const matchEnd = matchStart + toSearch.length;
  return new Set(ranges.filter(r => r.end > matchStart && r.start < matchEnd).map(r => r.idx));
}

export default function SnapPdfPanel({ panel, onClose }) {
  const [numPages, setNumPages] = useState(null);
  const [currentPage, setCurrentPage] = useState(null);
  const [matchedIndices, setMatchedIndices] = useState(new Set());
  const attemptsRef = useRef(0);
  const lockedRef = useRef(false);
  const foundPageRef = useRef(null);
  const viewerRef = useRef(null);

  const { page, quote, highlight_text, section } = panel || {};

  // Reset whenever a new citation is opened.
  useEffect(() => {
    if (page) {
      setCurrentPage(page);
      setMatchedIndices(new Set());
      attemptsRef.current = 0;
      lockedRef.current = false;
      foundPageRef.current = null;
    }
  }, [page, highlight_text]);

  // Called by react-pdf once the text layer items are available for the current page.
  // We search using highlight_text (real extracted snippet) rather than the LLM quote
  // to avoid paraphrase mismatches. If nothing matches, advance the page (lookahead).
  const onGetTextSuccess = useCallback(({ items }) => {
    const pdfText = items.map(it => it.str).join(' ');
    // eslint-disable-next-line no-console
    console.log('[SNAP-HL] fired page:', currentPage, 'locked:', lockedRef.current);
    // eslint-disable-next-line no-console
    console.log('[SNAP-HL] highlight_text:', highlight_text?.slice(0, 100));
    // eslint-disable-next-line no-console
    console.log('[SNAP-HL] pdf text (first 300):', pdfText.slice(0, 300));
    if (lockedRef.current || !highlight_text) return;

    const matched = findMatchedIndices(items, highlight_text);
    if (matched.size > 0) {
      setMatchedIndices(matched);
      lockedRef.current = true;
      foundPageRef.current = currentPage;
    } else if (attemptsRef.current < MAX_LOOKAHEAD) {
      attemptsRef.current += 1;
      setCurrentPage(p => p + 1);
    }
  }, [highlight_text, currentPage]);

  // Scroll to the first highlighted span once matchedIndices are set.
  useEffect(() => {
    if (matchedIndices.size === 0) return;
    const timer = setTimeout(() => {
      const mark = viewerRef.current?.querySelector('.snap-pdf-hl');
      if (mark) mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, 300);
    return () => clearTimeout(timer);
  }, [matchedIndices]);

  // customTextRenderer receives itemIndex from react-pdf — the same index used
  // in onGetTextSuccess. No string matching needed here.
  const customTextRenderer = useCallback(({ str, itemIndex }) => {
    const s = esc(str);
    if (foundPageRef.current !== null && currentPage !== foundPageRef.current) return s;
    return matchedIndices.has(itemIndex) ? `<mark class="snap-pdf-hl">${s}</mark>` : s;
  }, [matchedIndices, currentPage]);

  if (!panel) return null;

  return (
    <>
      <div className="snap-pdf-backdrop" onClick={onClose} />

      <div className="snap-pdf-panel snap-pdf-panel--open">
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

        {quote && (
          <div className="snap-pdf-callout">
            <span className="snap-pdf-callout-label">Cited text</span>
            <span className="snap-pdf-callout-quote">"{quote}"</span>
          </div>
        )}

        <div className="snap-pdf-viewer" ref={viewerRef}>
          <Document
            file={`${process.env.REACT_APP_API_URL || ''}/api/snap/pdf`}
            onLoadSuccess={({ numPages }) => setNumPages(numPages)}
            loading={<div className="snap-pdf-status">Loading PDF…</div>}
            error={<div className="snap-pdf-status snap-pdf-status--err">Could not load PDF.</div>}
          >
            <Page
              key={`${currentPage}-${highlight_text}`}
              pageNumber={currentPage || 1}
              width={Math.min(560, window.innerWidth * 0.92)}
              customTextRenderer={customTextRenderer}
              onGetTextSuccess={onGetTextSuccess}
              renderAnnotationLayer={false}
            />
          </Document>
        </div>

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
            href={`${process.env.REACT_APP_API_URL || ''}/api/snap/pdf#page=${currentPage}`}
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
