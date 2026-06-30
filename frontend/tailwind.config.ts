import type { Config } from 'tailwindcss'
import { fontFamily } from 'tailwindcss/defaultTheme'

const config: Config = {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: {
      center: true,
      padding: '2rem',
      screens: { '2xl': '1400px' },
    },
    extend: {
      colors: {
        // Matcha — the brand green as a full utility scale. The app's accent
        // utilities (chips, score bars, progress) reference this directly; the
        // CSS-var `primary` carries the same green for the themed chrome.
        matcha: {
          50: '#f4f7ec',
          100: '#e7efce',
          200: '#cfe0a4',
          300: '#b2cd76',
          400: '#97b850',
          500: '#7d9e37',
          600: '#62802b',
          700: '#4b6224',
          800: '#3d4f21',
          900: '#33431f',
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        sidebar: 'hsl(var(--sidebar))',
        primary: {
          DEFAULT: 'hsl(var(--primary))',
          foreground: 'hsl(var(--primary-foreground))',
          hover: 'hsl(var(--primary-hover))',
          subtle: 'hsl(var(--primary-subtle))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--secondary))',
          foreground: 'hsl(var(--secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--destructive))',
          foreground: 'hsl(var(--destructive-foreground))',
          subtle: 'hsl(var(--destructive-subtle))',
        },
        muted: {
          DEFAULT: 'hsl(var(--muted))',
          foreground: 'hsl(var(--muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--accent))',
          foreground: 'hsl(var(--accent-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--card))',
          foreground: 'hsl(var(--card-foreground))',
        },
        success: {
          DEFAULT: 'hsl(var(--success))',
          foreground: 'hsl(var(--success-foreground))',
          subtle: 'hsl(var(--success-subtle))',
        },
        warning: {
          DEFAULT: 'hsl(var(--warning))',
          foreground: 'hsl(var(--warning-foreground))',
          subtle: 'hsl(var(--warning-subtle))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      // Warm, paper-tinted elevation (shadows lean brown, never gray)
      boxShadow: {
        sm: '0 1px 3px hsl(32 30% 30% / 0.07), 0 1px 2px hsl(32 30% 30% / 0.05)',
        DEFAULT: '0 2px 6px hsl(32 28% 28% / 0.07), 0 1px 2px hsl(32 28% 28% / 0.05)',
        md: '0 4px 12px hsl(32 28% 28% / 0.08), 0 2px 4px hsl(32 28% 28% / 0.05)',
        lg: '0 12px 28px hsl(32 28% 25% / 0.10), 0 4px 10px hsl(32 28% 25% / 0.06)',
      },
      fontFamily: {
        sans: ['Inter', ...fontFamily.sans],
        mono: ['JetBrains Mono', ...fontFamily.mono],
        // A soft optical serif used sparingly for the brand wordmark and a few
        // hero headings — gives the "paper & matcha" surfaces some personality
        // without touching the workhorse body/UI text (which stays Inter).
        display: ['Fraunces', ...fontFamily.serif],
      },
      keyframes: {
        'accordion-down': {
          from: { height: '0' },
          to: { height: 'var(--radix-accordion-content-height)' },
        },
        'accordion-up': {
          from: { height: 'var(--radix-accordion-content-height)' },
          to: { height: '0' },
        },
      },
      animation: {
        'accordion-down': 'accordion-down 0.2s ease-out',
        'accordion-up': 'accordion-up 0.2s ease-out',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}

export default config
