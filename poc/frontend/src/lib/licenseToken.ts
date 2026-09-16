/** Extract the license token from an uploaded file: a JSON wrapper
 * (license_token/license_key/token, string values only), or — for a raw
 * delivery that may include CLI preamble or a label — the longest `base64.base64`
 * token substring found anywhere in the text. Returns '' when none is found so
 * the caller can show a clear "no token" message instead of posting garbage.
 *
 * The token is a credential: never log the input or the return value. */
export function extractToken(raw: string): string {
  const t = raw.trim()
  if (!t) return ''
  try {
    const obj = JSON.parse(t)
    const v = obj.license_token ?? obj.license_key ?? obj.token
    if (typeof v === 'string' && v.trim()) return v.trim()
  } catch {
    /* not JSON */
  }
  // Match a two-segment base64 token even when it's inline after a label
  // (e.g. "Token: ey....ey...") — not just on its own line.
  const matches = t.match(/[A-Za-z0-9+/=_-]{20,}\.[A-Za-z0-9+/=_-]{20,}/g)
  if (matches && matches.length) return matches.sort((a, b) => b.length - a.length)[0]
  return ''
}
