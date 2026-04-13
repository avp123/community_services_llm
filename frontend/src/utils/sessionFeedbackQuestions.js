/**
 * Session feedback survey copy (q1/q2). IDs must match conversation_feedback columns.
 */

export const SESSION_FEEDBACK_QUESTIONS = [
  {
    id: 'q1',
    label: 'How effective was PeerCoPilot at assisting with this member during this session?',
    helper: '1 = not at all effective · 5 = very effective',
  },
  {
    id: 'q2',
    label: 'How did PeerCoPilot affect the human connection with the member during this session?',
    helper: '1 = significantly detracted · 5 = significantly enhanced',
  },
];

/** Legacy columns (older 5-question survey); shown only in read-only viewer when present. */
export const LEGACY_FEEDBACK_QUESTIONS = [
  { id: 'q3', label: 'Earlier saved rating (legacy question 3)' },
  { id: 'q4', label: 'Earlier saved rating (legacy question 4)' },
  { id: 'q5', label: 'Earlier saved rating (legacy question 5)' },
];

/**
 * @param {Record<string, unknown>} feedback API payload from get_session_feedback
 * @returns {boolean}
 */
export function feedbackPayloadHasAnyAnswer(feedback) {
  if (!feedback || typeof feedback !== 'object') return false;
  const text = feedback.feedback_text;
  if (typeof text === 'string' && text.trim() !== '') return true;
  for (const k of ['q1', 'q2', 'q3', 'q4', 'q5']) {
    const v = feedback[k];
    if (v !== null && v !== undefined && v !== '') return true;
  }
  return false;
}
