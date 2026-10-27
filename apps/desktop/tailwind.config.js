/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        kairos: {
          bg: '#090D16',
          panel: '#0F1624',
          card: '#151E30',
          border: '#1F2C45',
          accent: '#10B981',
          cyan: '#06B6D4',
          purple: '#8B5CF6',
          amber: '#F59E0B',
        },
      },
    },
  },
  plugins: [],
};
