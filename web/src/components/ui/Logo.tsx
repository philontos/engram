// Engram logo — wordmark + mark.
//
// Design notes:
//   - Cormorant Garamond, weight 400, all caps, wide letter-spacing.
//     The wide tracking is the brand signature; tighten it and the logo
//     loses its "literary press" character.
//   - The arc is a subtle mauve accent beneath the wordmark, suggesting
//     "holding / mirror / memory" without literalism. Toggle off via
//     `accent={false}` for a pure-typography variant.
//   - Inherits color from `currentColor`, so it adapts to text-primary in
//     either theme. The arc is mauve regardless.

import { useTheme } from '@/lib/theme'

type LogoSize = 'sm' | 'md' | 'lg' | 'hero'
type Variant = 'wordmark' | 'mark'

const SIZES: Record<LogoSize, { fontSize: number; letterSpacing: number; arcGap: number; arcStroke: number }> = {
  sm:   { fontSize: 16, letterSpacing: 3,  arcGap: 4,  arcStroke: 1   },
  md:   { fontSize: 28, letterSpacing: 5,  arcGap: 6,  arcStroke: 1.2 },
  lg:   { fontSize: 44, letterSpacing: 8,  arcGap: 9,  arcStroke: 1.4 },
  hero: { fontSize: 72, letterSpacing: 14, arcGap: 14, arcStroke: 1.6 },
}

export function Logo({
  size = 'md',
  variant = 'wordmark',
  accent = true,
  tagline,
  style,
}: {
  size?: LogoSize
  variant?: Variant
  accent?: boolean
  tagline?: string
  style?: React.CSSProperties
}) {
  const { palette } = useTheme()
  const s = SIZES[size]

  if (variant === 'mark') {
    // Square monogram — uppercase E with the same arc treatment.
    // Used in nav rails, favicons, avatars.
    const dim = s.fontSize * 1.5
    return (
      <span
        aria-label="Engram"
        style={{
          display: 'inline-flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
          width: dim, height: dim,
          ...style,
        }}>
        <span style={{
          fontFamily: "'Cormorant Garamond', Georgia, serif",
          fontWeight: 400,
          fontSize: s.fontSize,
          lineHeight: 1,
          color: 'currentColor',
        }}>E</span>
        {accent && (
          <svg width={s.fontSize * 0.7} height={s.arcGap + s.arcStroke + 1}
               viewBox={`0 0 ${s.fontSize * 0.7} ${s.arcGap + s.arcStroke + 1}`}
               style={{ marginTop: 2 }} aria-hidden>
            <path
              d={`M 1 1 Q ${s.fontSize * 0.35} ${s.arcGap} ${s.fontSize * 0.7 - 1} 1`}
              stroke={palette.mauve}
              strokeWidth={s.arcStroke}
              strokeLinecap="round"
              fill="none" />
          </svg>
        )}
      </span>
    )
  }

  // Full wordmark
  return (
    <span aria-label="Engram"
      style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'center', ...style }}>
      <span style={{
        fontFamily: "'Cormorant Garamond', 'Noto Serif SC', Georgia, serif",
        fontWeight: 400,
        fontSize: s.fontSize,
        letterSpacing: s.letterSpacing,
        lineHeight: 1,
        color: 'currentColor',
        // The trailing letter inherits the letter-spacing — visually it pulls
        // the word right of center. Compensate by nudging it left slightly.
        paddingLeft: s.letterSpacing,
      }}>ENGRAM</span>
      {accent && (
        <svg
          width={s.fontSize * 4}
          height={s.arcGap + s.arcStroke + 1}
          viewBox={`0 0 ${s.fontSize * 4} ${s.arcGap + s.arcStroke + 1}`}
          style={{ marginTop: Math.max(2, s.fontSize * 0.08) }}
          aria-hidden>
          <path
            d={`M ${s.fontSize * 0.6} 1 Q ${s.fontSize * 2} ${s.arcGap} ${s.fontSize * 3.4} 1`}
            stroke={palette.mauve}
            strokeWidth={s.arcStroke}
            strokeLinecap="round"
            fill="none"
          />
        </svg>
      )}
      {tagline && (
        <span style={{
          marginTop: Math.max(8, s.fontSize * 0.18),
          fontFamily: "'Cormorant Garamond', 'Noto Serif SC', Georgia, serif",
          fontStyle: 'italic',
          fontSize: Math.max(11, s.fontSize * 0.26),
          letterSpacing: 0.5,
          color: 'var(--engram-text-muted)',
          lineHeight: 1.4,
        }}>{tagline}</span>
      )}
    </span>
  )
}
