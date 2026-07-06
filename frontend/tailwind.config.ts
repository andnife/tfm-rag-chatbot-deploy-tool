import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{ts,tsx}', './src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          50: 'var(--color-primary-50)',
          100: 'var(--color-primary-100)',
          200: 'var(--color-primary-200)',
          300: 'var(--color-primary-300)',
          400: 'var(--color-primary-400)',
          500: 'var(--color-primary-500)',
          600: 'var(--color-primary-600)',
          700: 'var(--color-primary-700)',
          800: 'var(--color-primary-800)',
          900: 'var(--color-primary-900)',
          DEFAULT: 'var(--color-primary-600)',
        },
        gray: {
          50: 'var(--color-gray-50)',
          100: 'var(--color-gray-100)',
          200: 'var(--color-gray-200)',
          300: 'var(--color-gray-300)',
          400: 'var(--color-gray-400)',
          500: 'var(--color-gray-500)',
          600: 'var(--color-gray-600)',
          700: 'var(--color-gray-700)',
          800: 'var(--color-gray-800)',
          900: 'var(--color-gray-900)',
        },
        canvas: 'var(--canvas)',
        surface: { DEFAULT: 'var(--surface)', 2: 'var(--surface-2)' },
        line: { DEFAULT: 'var(--border)', muted: 'var(--border-muted)' },
        fg: { DEFAULT: 'var(--fg)', muted: 'var(--fg-muted)', faint: 'var(--fg-faint)' },
        accent: {
          DEFAULT: 'var(--accent)',
          hover: 'var(--accent-hover)',
          fg: 'var(--accent-fg)',
          subtle: 'var(--accent-subtle)',
          border: 'var(--accent-border)',
        },
        link: 'var(--link)',
        // shadcn-convention aliases (used across eval components) → mapped to our
        // flipping semantic tokens so `bg-card`, `text-muted-foreground`,
        // `border-border`, `text-foreground`, `bg-muted`, `text-destructive`, etc. resolve.
        background: 'var(--surface)',
        foreground: 'var(--fg)',
        card: { DEFAULT: 'var(--canvas)', foreground: 'var(--fg)' },
        popover: { DEFAULT: 'var(--canvas)', foreground: 'var(--fg)' },
        muted: { DEFAULT: 'var(--surface-2)', foreground: 'var(--fg-muted)' },
        border: 'var(--border)',
        input: 'var(--border)',
        ring: 'var(--accent)',
        destructive: { DEFAULT: 'var(--color-danger)', foreground: 'var(--accent-fg)' },
        success: { DEFAULT: 'var(--color-success)', subtle: 'var(--color-success-light)' },
        warning: { DEFAULT: 'var(--color-warning)', subtle: 'var(--color-warning-light)' },
        danger: { DEFAULT: 'var(--color-danger)', subtle: 'var(--color-danger-light)' },
        info: { DEFAULT: 'var(--color-info)', subtle: 'var(--color-info-light)' },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
      },
      boxShadow: {
        xs: 'var(--shadow-xs)',
        sm: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        xl: 'var(--shadow-xl)',
      },
    },
  },
  plugins: [],
}
export default config
