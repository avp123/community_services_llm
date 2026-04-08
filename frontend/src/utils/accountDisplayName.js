/** Shown in nav / greetings when set; login id stays in `user.username`. */
export const USER_DISPLAY_NAME_KEY = 'userDisplayName';

export const DISPLAY_NAME_MAX_LENGTH = 15;


/** Prefer display name when set; otherwise username (for UI labels only). */
export function getUserIdentityLabel(user) {
  if (!user) return '';
  const dn = user.displayName && String(user.displayName).trim();
  return dn || user.username || '';
}

export function readStoredDisplayName() {
  return (localStorage.getItem(USER_DISPLAY_NAME_KEY) || '').trim();
}

export function writeStoredDisplayName(displayName) {
  const v = String(displayName || '').trim();
  if (v) localStorage.setItem(USER_DISPLAY_NAME_KEY, v);
  else localStorage.removeItem(USER_DISPLAY_NAME_KEY);
  return v;
}
