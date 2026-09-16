/* Clipboard writes that fail loudly.
 *
 * `void navigator.clipboard?.writeText(x)` followed by an unconditional
 * "已复制" is wrong twice over: optional chaining swallows a MISSING Clipboard
 * API, which is exactly what happens on any http:// (non-localhost) origin —
 * and this product ships to on-prem gateways served over plain HTTP — while a
 * REJECTED write becomes an unhandled promise rejection rather than something
 * the caller can react to. The analyst sees "已复制", pastes into the incident
 * ticket, and gets whatever was on the clipboard before.
 */

import { translate } from '@/lib/i18n'
import { libCopy } from '@/locales/lib'

export class ClipboardUnavailable extends Error {}

/** Write text to the clipboard, throwing if it did not happen. */
export async function copyText(text: string): Promise<void> {
  if (!navigator.clipboard?.writeText) {
    throw new ClipboardUnavailable(translate(libCopy, 'clipboardUnavailable'))
  }
  await navigator.clipboard.writeText(text)
}
