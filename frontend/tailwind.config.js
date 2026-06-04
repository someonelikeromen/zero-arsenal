/**
 * Tailwind v4 配置（通过 src/index.css 的 @config 指令加载）。
 * v4 引擎下 content 用于显式声明扫描范围；theme.extend 可继续按需扩展。
 * @type {import('tailwindcss').Config}
 */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {},
  },
  plugins: [],
}
