import { translate } from '@/lib/i18n'
import { libCopy, type LibKey } from '@/locales/lib'

/*
 * Frontend error classifier. The gateway already passes through ES/LLM error
 * messages (backend has `friendly_es_error`), but a raw `parsing_exception`
 * means little to an analyst. This maps the common substrings to a short
 * hint (looked up in the current UI language) plus whether an AI "fix it with
 * the error" retry makes sense.
 *
 * It never changes the original message — it only adds guidance beside it.
 */

export interface ErrorHelp {
  /** One-line cause/advice in the current UI language, or null when we have
      nothing to add. */
  hint: string | null
  /** True when re-running generation with the error fed back is likely to help. */
  retryable: boolean
}

interface Rule {
  test: RegExp
  hintKey: LibKey
  retryable?: boolean
}

// Ordered — first match wins, so put the specific patterns before the generic.
const RULES: Rule[] = [
  {
    test: /fielddata is disabled|set fielddata=true|use a keyword field/i,
    hintKey: 'errTextFielddata',
    retryable: true,
  },
  {
    test: /parsing_exception|x_content_parse_exception|failed to parse|unknown key|json_parse/i,
    hintKey: 'errParsing',
    retryable: true,
  },
  {
    test: /index_not_found_exception|no such index/i,
    hintKey: 'errIndexNotFound',
    retryable: false,
  },
  {
    test: /search_phase_execution_exception/i,
    hintKey: 'errSearchPhase',
    retryable: true,
  },
  {
    test: /illegal_argument_exception/i,
    hintKey: 'errIllegalArgument',
    retryable: true,
  },
  {
    test: /too_many_clauses|maxClauseCount/i,
    hintKey: 'errTooManyClauses',
    retryable: true,
  },
  {
    test: /DSL 校验失败|只读|read[- ]?only|forbidden (?:dsl|operation)|script.*not allowed|runtime_mappings/i,
    hintKey: 'errReadOnly',
    retryable: true,
  },
  {
    // 请求过于频繁 is the gateway's own 429 text (backend/rate_limit.py). It used
    // to answer in English, which `too many requests` caught; without this the
    // rule stopped matching the moment that message was translated.
    test: /\b429\b|rate.?limit|too many requests|请求过于频繁|quota|配额/i,
    hintKey: 'errRateLimited',
    retryable: false,
  },
  {
    test: /timed? ?out|timeout|deadline/i,
    hintKey: 'errTimeout',
    retryable: false,
  },
  {
    test: /revoked|FeatureLocked|license|未激活|expired/i,
    hintKey: 'errLicense',
    retryable: false,
  },
  {
    test: /failed to fetch|networkerror|econnrefused|502|503|504|gateway/i,
    hintKey: 'errUnreachable',
    retryable: false,
  },
]

export function classifyError(message: string | null | undefined): ErrorHelp {
  const msg = (message ?? '').toString()
  if (!msg.trim()) return { hint: null, retryable: false }
  for (const r of RULES) {
    if (r.test.test(msg))
      return { hint: translate(libCopy, r.hintKey), retryable: !!r.retryable }
  }
  return { hint: null, retryable: false }
}
