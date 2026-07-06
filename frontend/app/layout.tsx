import type { Metadata } from 'next'
import { Providers } from './providers'
import '@/styles/globals.css'

export const metadata: Metadata = { title: 'RAG Chatbot Platform' }

// Applied before hydration so a dark-mode refresh paints dark immediately
// (no flash to light) and the <html> class matches what the client renders.
// Keep the storage key in sync with src/lib/themeStore.ts (KEY = 'tfm_rag_theme').
const THEME_INIT = `(function(){try{if(localStorage.getItem('tfm_rag_theme')==='dark'){document.documentElement.classList.add('dark')}}catch(e){}})();`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
