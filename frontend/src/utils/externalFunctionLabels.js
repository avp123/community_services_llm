/** OpenAI function names → user-facing labels (Usage Analytics, Chat history). */
const EXTERNAL_FUNCTION_LABELS = {
  resources_tool: 'Resources',
  library_tool: 'Library',
  directions_tool: 'Directions',
  calculator_tool: 'Calculator',
  web_search_tool: 'Web Search',
  check_eligibility: 'Benefits eligibility',
};

/**
 * @param {string} internalName
 * @returns {string}
 */
export function getExternalFunctionLabel(internalName) {
  if (!internalName || typeof internalName !== 'string') return internalName || '';
  if (Object.prototype.hasOwnProperty.call(EXTERNAL_FUNCTION_LABELS, internalName)) {
    return EXTERNAL_FUNCTION_LABELS[internalName];
  }
  const stripped = internalName.replace(/_tool$/i, '');
  return stripped
    .split('_')
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
}
