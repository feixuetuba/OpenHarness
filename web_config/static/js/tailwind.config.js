tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        'dark-bg': '#0a0e1a',
        'dark-bg-secondary': '#0f1629',
        'dark-card': '#141b2d',
        'dark-card-hover': '#1a2340',
        'dark-border': '#1e293b',
        'dark-border-light': '#334155',
        'accent-green': '#34d399',
        'accent-green-dark': '#059669',
        'accent-blue': '#60a5fa',
        'accent-purple': '#a78bfa',
        'accent-amber': '#fbbf24',
        'text-primary': '#f1f5f9',
        'text-secondary': '#94a3b8',
        'text-muted': '#64748b',
      },
      fontFamily: {
        'sans': ['Inter', 'system-ui', 'sans-serif'],
        'mono': ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        'soft': '0 2px 8px rgba(0, 0, 0, 0.3)',
        'glow': '0 0 20px rgba(52, 211, 153, 0.15)',
        'glow-purple': '0 0 20px rgba(167, 139, 250, 0.15)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
    }
  }
}