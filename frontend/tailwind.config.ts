import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        neo: {
          bg: "#FFFDF8",
          ink: "#1e293b",
          accent: "#ffb3c6", // Pastel pink
          secondary: "#fdf0b0", // Buttery yellow
          muted: "#c4b5fd", // Lavender
          green: "#a7f3d0", // Mint green
          blue: "#bfdbfe", // Baby blue
          white: "#FFFFFF",
        },
      },
      fontFamily: {
        sans: [
          "Space Grotesk",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
        mono: ["Space Grotesk", "monospace"],
      },
      boxShadow: {
        "neo-xs": "2px 3px 0px 0px #1e293b",
        "neo-sm": "3px 4px 0px 0px #1e293b",
        neo: "4px 6px 0px 0px #1e293b",
        "neo-lg": "6px 8px 0px 0px #1e293b",
        "neo-xl": "8px 12px 0px 0px #1e293b",
      },
      animation: {
        "stamp-in": "stampIn 0.25s ease-out",
        "float-tag": "floatTag 2.8s ease-in-out infinite",
        "pulse-dot": "pulseDot 1s linear infinite",
        "slide-up": "slideUp 0.3s ease-out",
        "slide-right": "slideRight 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
        "fade-in": "fadeIn 0.2s ease-out",
        "gentle-pulse": "gentlePulse 1.5s ease-in-out infinite",
        "dot-bounce": "dotBounce 0.6s ease-in-out infinite",
      },
      keyframes: {
        stampIn: {
          "0%": {
            opacity: "0",
            transform: "translateY(14px) rotate(-2deg)",
          },
          "100%": {
            opacity: "1",
            transform: "translateY(0) rotate(0deg)",
          },
        },
        floatTag: {
          "0%, 100%": { transform: "rotate(-3deg) translateY(0)" },
          "50%": { transform: "rotate(1deg) translateY(-3px)" },
        },
        pulseDot: {
          "0%, 100%": { transform: "translateY(0)", opacity: "0.4" },
          "50%": { transform: "translateY(-3px)", opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideRight: {
          "0%": { opacity: "0", transform: "translateX(100%)" },
          "100%": { opacity: "1", transform: "translateX(0)" },
        },
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        gentlePulse: {
          "0%, 100%": { opacity: "0.6" },
          "50%": { opacity: "1" },
        },
        dotBounce: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(-4px)" },
        },
      },
    },
  },
  plugins: [],
};

export default config;
