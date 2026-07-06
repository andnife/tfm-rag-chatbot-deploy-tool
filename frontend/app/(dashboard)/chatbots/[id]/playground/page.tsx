'use client'

import { useRef, useState, useEffect } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ChatComposer } from '@/components/features/ChatComposer'
import { ChatMessage } from '@/components/features/ChatMessage'
import { IterationPanel } from '@/components/features/IterationPanel'
import { useChat, useChatbot, useMe } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { Citation, RetrievalIteration } from '@/types/api'

interface Turn {
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
}

export default function PlaygroundPage() {
  const { t } = useTranslation()
  const params = useParams<{ id: string }>()
  const id = params.id ?? ''
  const { data: bot } = useChatbot(id)
  const { data: me } = useMe()
  const chat = useChat(id)
  const previewName = me?.email ? me.email.split('@')[0] : ''
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [iterations, setIterations] = useState<RetrievalIteration[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns])

  const onSend = (message: string) => {
    setTurns(t => [...t, { role: 'user', content: message }])
    chat.mutate({ message, session_id: sessionId }, {
      onSuccess: (res) => {
        setSessionId(res.session_id)
        setTurns(t => [...t, { role: 'assistant', content: res.content, citations: res.citations }])
        setIterations(res.iterations)
      },
      onError: (err) => {
        toast.error(err instanceof ApiError ? err.message : t('playground.errorChat'))
        setTurns(t => t.slice(0, -1))
      },
    })
  }

  const onReset = () => { setSessionId(null); setTurns([]); setIterations([]) }

  return (
    <AppShell title={bot?.name ? `${t('playground.title')} · ${bot.name}` : t('playground.title')}>
      <div className="mb-4">
        <Link href="/chatbots" className="text-sm text-primary-600 hover:underline inline-flex items-center">
          <ArrowLeft className="h-4 w-4 mr-1" /> {t('common.back')}
        </Link>
      </div>
      <Tabs defaultValue="debug">
        <TabsList>
          <TabsTrigger value="debug">{t('playground.tabDebug')}</TabsTrigger>
          <TabsTrigger value="preview">{t('playground.tabPreview')}</TabsTrigger>
        </TabsList>

        <TabsContent value="debug">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 lg:h-[calc(100vh-15rem)]">
            <div className="lg:col-span-2 flex flex-col gap-4 min-h-0 h-[60vh] lg:h-auto">
              <Card className="flex-1 flex flex-col min-h-0">
                <CardContent className="flex-1 overflow-y-auto p-4 space-y-3" ref={scrollRef}>
                  {turns.length === 0 && (
                    <p className="text-fg-faint text-center py-12 text-sm">{t('sessions.startConversation')}</p>
                  )}
                  {turns.map((turn, i) => <ChatMessage key={i} {...turn} />)}
                  {chat.isPending && <ChatMessage role="assistant" content="..." />}
                </CardContent>
                <div className="p-4 border-t border-line">
                  <ChatComposer onSend={onSend} disabled={chat.isPending} />
                </div>
              </Card>
            </div>
            <div className="space-y-4 lg:overflow-y-auto">
              <Card>
                <CardHeader><CardTitle className="text-sm">{t('sessions.sessionLabel')}</CardTitle></CardHeader>
                <CardContent className="text-xs space-y-2">
                  <div className="text-fg-muted font-mono break-all">{sessionId ?? t('sessions.noSession')}</div>
                  <div className="text-fg-muted">{turns.filter(turn => turn.role === 'user').length} {t('sessions.messages')}</div>
                  <Button size="sm" variant="secondary" onClick={onReset}>{t('sessions.newSession')}</Button>
                </CardContent>
              </Card>
              <IterationPanel iterations={iterations} />
            </div>
          </div>
        </TabsContent>

        <TabsContent value="preview">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">{t('playground.previewTitle')}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              <p className="text-xs text-fg-muted">{t('playground.previewHint')}</p>
              {bot?.public_key ? (
                <div className="relative bg-surface rounded-lg h-[60vh] overflow-hidden border border-line">
                  <iframe
                    title="widget-preview"
                    className="w-full h-full bg-white"
                    sandbox="allow-scripts allow-same-origin"
                    srcDoc={`<!doctype html>
<html lang="es"><head><meta charset="utf-8" />
<style>html,body{margin:0;height:100%;background:#f8fafc;font-family:Inter,system-ui,sans-serif}</style>
</head>
<body>
<div style="padding:24px;color:#94a3b8;font-size:13px;text-align:center">
${t('playground.previewHostNote')}
</div>
<script
  src="${typeof window !== 'undefined' ? window.location.origin : ''}/widget/widget.js"
  data-public-key="${bot.public_key}"
  data-api-base="${typeof window !== 'undefined' ? window.location.origin : ''}"
  data-user-name="${previewName}"
  async
></script>
</body></html>`}
                  />
                </div>
              ) : (
                <p className="text-fg-faint text-sm text-center py-12">{t('widget.previewLoading')}</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </AppShell>
  )
}
