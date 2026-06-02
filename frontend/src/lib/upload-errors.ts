/**
 * Translate raw API/LLM error messages into something a user can act on.
 *
 * Backend errors include things like
 *   "Could not extract data from invoice.pdf: 429 rate limit exceeded"
 *   "schema mismatch: Field required at..."
 *
 * Users don't need to see "schema mismatch". They need to know what to do.
 */

export function humanizeUploadError(raw: string): string {
  const msg = String(raw).toLowerCase()

  if (/rate.?limit|429|throttl|quota.?exceeded/.test(msg)) {
    return 'Hit upload rate limit — try again in a moment.'
  }
  if (/schema|invalid.?json|model.?validate|parseable/.test(msg)) {
    return "AI couldn't read this file clearly. Try retrying or add manually."
  }
  if (/unsupported.?(file|mime|type)|415/.test(msg)) {
    return 'File type not supported. Use PDF, PNG, JPG or WEBP.'
  }
  if (/network|timeout|econnreset|fetch.?failed|connect/.test(msg)) {
    return 'Network hiccup. Check connection and retry.'
  }
  if (/encrypted|password/.test(msg)) {
    return 'PDF is password-protected. Remove the password and retry.'
  }
  if (/has no pages|empty|no text/.test(msg)) {
    return 'File appears to be empty or unreadable.'
  }
  if (/no api.?key|api.?key.?(not|missing)|credentials/.test(msg)) {
    return 'AI extraction service is not configured. Contact admin.'
  }
  if (/422|could not extract|extraction failed/.test(msg)) {
    return "AI couldn't extract data — try retrying or upload a clearer file."
  }

  // Default: strip the boilerplate prefix, truncate if long
  const cleaned = raw
    .replace(/^extraction failed:\s*/i, '')
    .replace(/^could not extract data from \S+:\s*/i, '')
    .replace(/^request failed with status code \d+\s*/i, '')
  return cleaned.length > 100 ? cleaned.slice(0, 100) + '…' : cleaned
}
