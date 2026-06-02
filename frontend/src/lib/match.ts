/**
 * Human translation layer for the matching engine.
 *
 * The backend exposes raw fields — score 0..1, method strings like
 * "fuzzy+embed", reason strings like "exact amount, 8d apart, name fuzzy (83%)".
 * The user shouldn't see any of that vocabulary.
 *
 * Everything that surfaces match results in the UI imports from here.
 */

export type MatchStrength = 'strong' | 'likely' | 'possible' | 'weak'

export interface MatchView {
  strength: MatchStrength
  label: string          // "Strong match" / "Likely match" / ...
  variant: 'success' | 'warning' | 'muted'
  /** Friendly one-liner explaining what matched and what didn't. */
  reasonText: string
  /** Whether the suggestion is confident enough to show side-by-side by default. */
  showByDefault: boolean
  /** Whether to apply the full green-card treatment. */
  fullHighlight: boolean
  /** Whether to highlight matching fields individually (75-89%). */
  fieldHighlight: boolean
  /** Which fields the reason claims to be a match for. */
  fields: {
    amount: boolean
    date: boolean
    name: boolean
  }
}

/** Friendly label for the cascade method. Internal naming hidden. */
const METHOD_TEXT: Record<string, string> = {
  'alias-exact': 'known alias',
  'canonical-exact': 'same name',
  'fuzzy': 'similar name',
  'fuzzy+embed': 'similar name',
  'no-name': '',
}

const HIGH = 0.9
const MID_HIGH = 0.75
const MID_LOW = 0.65

export function viewFor(score: number, method: string, rawReason: string): MatchView {
  let strength: MatchStrength
  let label: string
  let variant: 'success' | 'warning' | 'muted'

  if (score >= HIGH) {
    strength = 'strong'; label = 'Strong match'; variant = 'success'
  } else if (score >= MID_HIGH) {
    strength = 'likely'; label = 'Likely match'; variant = 'success'
  } else if (score >= MID_LOW) {
    strength = 'possible'; label = 'Possible match'; variant = 'warning'
  } else {
    strength = 'weak'; label = 'Weak match'; variant = 'muted'
  }

  // Parse what the backend says matched
  const fields = {
    amount: /exact amount|≈ amount/.test(rawReason),
    // strict: only count as "date matched" if within 3 days
    date: /same day|^[1-3]d apart|·\s*[1-3]d apart/.test(rawReason),
    name: /name (canonical-exact|alias-exact|fuzzy)/.test(rawReason),
  }

  // Build a clean reason sentence
  const parts: string[] = []
  if (fields.amount) {
    parts.push(/exact amount/.test(rawReason) ? 'Same amount' : 'Amount close')
  } else if (/amount off by ([\d.]+)/.test(rawReason)) {
    const m = rawReason.match(/amount off by ([\d.]+)/)
    parts.push(`Amount off by ${m?.[1]}`)
  } else if (/amount differs by ([\d.]+)/.test(rawReason)) {
    const m = rawReason.match(/amount differs by ([\d.]+)/)
    parts.push(`Amount differs by ${m?.[1]}`)
  }

  if (/same day/.test(rawReason)) {
    parts.push('Same day')
  } else {
    const m = rawReason.match(/(\d+)d apart/)
    if (m) parts.push(`${m[1]} day${m[1] === '1' ? '' : 's'} apart`)
  }

  if (fields.name) {
    const methodText = METHOD_TEXT[method] || ''
    if (methodText) parts.push(methodText.charAt(0).toUpperCase() + methodText.slice(1))
  }

  return {
    strength,
    label,
    variant,
    reasonText: parts.join(' · ') || 'Low signal',
    showByDefault: score >= MID_LOW,
    fullHighlight: score >= HIGH,
    fieldHighlight: score >= MID_HIGH && score < HIGH,
    fields,
  }
}

/** Just the numeric → label mapping, for places that don't have a reason string. */
export function strengthFor(score: number): { strength: MatchStrength; label: string; variant: 'success' | 'warning' | 'muted' } {
  if (score >= HIGH) return { strength: 'strong', label: 'Strong', variant: 'success' }
  if (score >= MID_HIGH) return { strength: 'likely', label: 'Likely', variant: 'success' }
  if (score >= MID_LOW) return { strength: 'possible', label: 'Possible', variant: 'warning' }
  return { strength: 'weak', label: 'Weak', variant: 'muted' }
}

export const THRESHOLDS = { HIGH, MID_HIGH, MID_LOW }
