/** @type {import('next').NextConfig} */
const BACKEND = process.env.BACKEND_URL ?? 'http://localhost:8000'
const nextConfig = {
  output: 'standalone',
  // Chat sobre RAG con Ollama en CPU tarda minutos; el proxy de rewrites corta
  // a los 30s por defecto. Subimos el timeout para que el navegador espere.
  experimental: { proxyTimeout: 600_000 },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${BACKEND}/api/:path*` },
      { source: '/widget/:path*', destination: `${BACKEND}/widget/:path*` },
    ]
  },
}
module.exports = nextConfig
