/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        base: '#212121',
        elevated: '#2a2a2a',
        soft: '#1a1a1a',
        text: {
          primary: '#fafafa',
          secondary: '#a8a8a8',
          tertiary: '#6b6b6b',
        },
        border: {
          DEFAULT: '#3a3a3a',
          strong: '#525252',
        },
        accent: {
          DEFAULT: '#ff7759',
          soft: 'rgba(255,119,89,0.12)',
        },
        severity: {
          healthy: '#4ade80',
          watch: '#facc15',
          risk: '#fb923c',
          critical: '#ef4444',
        },
        'bg-base': '#212121',
        'bg-elevated': '#2a2a2a',
        'bg-soft': '#1a1a1a',
        'text-primary': '#fafafa',
        'text-secondary': '#a8a8a8',
        'text-tertiary': '#6b6b6b',
        'accent-soft': 'rgba(255, 119, 89, 0.12)',
        'border-strong': '#525252',
        'severity-healthy': '#4ade80',
        'severity-watch': '#facc15',
        'severity-risk': '#fb923c',
        'severity-critical': '#ef4444',
      },
      fontFamily: {
        serif: ['Instrument Serif', 'serif'],
        display: ['"Instrument Serif"', 'serif'],
        caption: ['Inter', 'sans-serif'],
        sans: ['Inter', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      fontSize: {
        'display': ['56px', { lineHeight: '1.1', letterSpacing: '-0.02em' }],
        'hero': ['36px', { lineHeight: '1.2', fontWeight: '600' }],
        'title': ['20px', { lineHeight: '1.3', fontWeight: '600' }],
        'body': ['14px', { lineHeight: '1.5', fontWeight: '400' }],
        'caption': ['12px', { lineHeight: '1.4', fontWeight: '500', letterSpacing: '0.04em' }],
        'mono': ['13px', { lineHeight: '1.5', fontWeight: '400' }],
      },
    },
  },
  plugins: [],
}
