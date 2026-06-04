export default {
  plugins: {
    // Tailwind v4 PostCSS 插件（替代 v3 的 tailwindcss + autoprefixer）。
    // v4 已内置 vendor 前缀处理，无需再挂载 autoprefixer。
    '@tailwindcss/postcss': {},
  },
}
