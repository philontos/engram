import { useI18n } from '@/i18n'
import { Languages } from 'lucide-react'

/** Vertical, icon-first switcher that fits the left sidebar. */
export function LangSwitcher() {
  const { lang, setLang } = useI18n()
  const next = lang === 'zh' ? 'en' : 'zh'
  const label = lang === 'zh' ? 'EN' : '中'

  return (
    <button
      onClick={() => setLang(next)}
      title={lang === 'zh' ? 'Switch to English' : '切换到中文'}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        padding: '10px 0', borderRadius: 10, width: '100%', cursor: 'pointer',
        border: 'none', background: 'transparent', color: 'var(--text3)',
        transition: 'all 0.12s',
      }}
    >
      <Languages size={17} strokeWidth={1.7} />
      <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: '0.04em' }}>{label}</span>
    </button>
  )
}
