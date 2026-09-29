// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

/** Semantic color tokens backed by CSS variables in src/styles/tokens.css (§B10). */
const token = (name) => `rgb(var(--color-${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        background: token("background"),
        surface: token("surface"),
        foreground: token("foreground"),
        muted: token("muted"),
        border: token("border"),
        primary: { DEFAULT: token("primary"), foreground: token("primary-foreground") },
        success: { DEFAULT: token("success"), surface: token("success-surface") },
        warning: token("warning"),
        danger: token("danger"),
        focus: token("focus"),
      },
    },
  },
  plugins: [],
};
