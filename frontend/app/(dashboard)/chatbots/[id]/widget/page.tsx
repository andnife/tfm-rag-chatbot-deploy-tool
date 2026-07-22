'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { ArrowLeft, Copy, Check, Sparkles } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useChatbot, useUpdateChatbot, useWelcomeSuggestions } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import { buildEmbedSnippet, buildConsoleSnippet } from '@/lib/widget-snippet'
import type { WidgetConfig } from '@/types/api'

export default function WidgetConfigPage() {
  const { t } = useTranslation()
  const params = useParams<{ id: string }>()
  const id = params.id ?? ''
  const { data: bot } = useChatbot(id)
  const update = useUpdateChatbot(id)
  const suggest = useWelcomeSuggestions(id)
  const [copied, setCopied] = useState(false)

  const wc: WidgetConfig = bot?.widget_config ?? {
    theme: 'light',
    primary_color: '#3b82f6',
    position: 'bottom-right',
    title: 'Asistente',
    welcome_message: '¡Hola! ¿En qué puedo ayudarte?',
    welcome_message_named: 'Hola {name}, ¿en qué puedo ayudarte?',
    placeholder: 'Escribe tu pregunta...',
    allowed_origins: ['*'],
  }

  const [theme, setTheme] = useState<WidgetConfig['theme']>(wc.theme)
  const [primaryColor, setPrimaryColor] = useState(wc.primary_color)
  const [position, setPosition] = useState<WidgetConfig['position']>(wc.position)
  const [title, setTitle] = useState(wc.title)
  const [welcomeMsg, setWelcomeMsg] = useState(wc.welcome_message)
  const [welcomeMsgNamed, setWelcomeMsgNamed] = useState(wc.welcome_message_named)
  const [placeholder, setPlaceholder] = useState(wc.placeholder)
  const [origins, setOrigins] = useState(wc.allowed_origins.join(', '))

  const onSave = () => {
    const allowed_origins = origins.split(',').map(s => s.trim()).filter(Boolean)
    update.mutate(
      { widget_config: { theme, primary_color: primaryColor, position, title, welcome_message: welcomeMsg, welcome_message_named: welcomeMsgNamed, placeholder, allowed_origins } },
      {
        onSuccess: () => toast.success(t('widget.saved')),
        onError: (err) => toast.error(err instanceof ApiError ? err.message : t('widget.errorSave')),
      },
    )
  }

  const onRegenerate = () => {
    suggest.mutate(undefined, {
      onSuccess: (s) => {
        setWelcomeMsg(s.welcome_message)
        setWelcomeMsgNamed(s.welcome_message_named)
        toast.success(t('widget.welcomeRegenerated'))
      },
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('widget.errorRegenerate')),
    })
  }

  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const publicKey = bot?.public_key ?? ''
  const [snippetMode, setSnippetMode] = useState<'embed' | 'console'>('embed')
  const embedSnippet = buildEmbedSnippet(origin, publicKey)
  const consoleSnippet = buildConsoleSnippet(origin, publicKey)
  const activeSnippet = snippetMode === 'embed' ? embedSnippet : consoleSnippet

  const onCopy = () => {
    navigator.clipboard.writeText(activeSnippet)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <AppShell title={bot?.name ? `${t('widget.title')} · ${bot.name}` : t('widget.title')}>
      <div className="mb-4">
        <Link href="/chatbots" className="text-sm text-primary-600 hover:underline inline-flex items-center">
          <ArrowLeft className="h-4 w-4 mr-1" /> {t('common.back')}
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Config */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">{t('widget.appearance')}</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>{t('widget.theme')}</Label>
                  <Select value={theme} onValueChange={v => setTheme(v as WidgetConfig['theme'])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="light">{t('theme.light')}</SelectItem>
                      <SelectItem value="dark">{t('theme.dark')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>{t('widget.position')}</Label>
                  <Select value={position} onValueChange={v => setPosition(v as WidgetConfig['position'])}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="bottom-right">{t('widget.positionRight')}</SelectItem>
                      <SelectItem value="bottom-left">{t('widget.positionLeft')}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
              <div className="space-y-2">
                <Label>{t('widget.primaryColor')}</Label>
                <div className="flex gap-2">
                  <input type="color" value={primaryColor} onChange={e => setPrimaryColor(e.target.value)} className="h-10 w-12 rounded border cursor-pointer" />
                  <Input value={primaryColor} onChange={e => setPrimaryColor(e.target.value)} placeholder="#3b82f6" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle className="text-sm">{t('widget.content')}</CardTitle>
              <Button
                size="sm"
                variant="secondary"
                onClick={onRegenerate}
                disabled={suggest.isPending}
                title={t('widget.welcomeRegenerateHint')}
              >
                <Sparkles className="h-4 w-4 mr-1" />
                {suggest.isPending ? t('widget.welcomeRegenerating') : t('widget.welcomeRegenerate')}
              </Button>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>{t('widget.widgetTitle')}</Label>
                <Input value={title} onChange={e => setTitle(e.target.value)} />
              </div>
              <div className="space-y-2">
                <Label>{t('widget.welcomeMessage')}</Label>
                <Input value={welcomeMsg} onChange={e => setWelcomeMsg(e.target.value)} />
                <p className="text-xs text-fg-muted">{t('widget.welcomeMessageHint')}</p>
              </div>
              <div className="space-y-2">
                <Label>{t('widget.welcomeMessageNamed')}</Label>
                <Input value={welcomeMsgNamed} onChange={e => setWelcomeMsgNamed(e.target.value)} />
                <p className="text-xs text-fg-muted">{t('widget.welcomeMessageNamedHint')}</p>
              </div>
              <div className="space-y-2">
                <Label>{t('widget.inputPlaceholder')}</Label>
                <Input value={placeholder} onChange={e => setPlaceholder(e.target.value)} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-sm">{t('widget.security')}</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>{t('widget.allowedOrigins')}</Label>
                <Input value={origins} onChange={e => setOrigins(e.target.value)} placeholder={t('widget.originPlaceholder')} />
                <p className="text-xs text-fg-muted">{t('widget.allowedOriginsHint')}</p>
              </div>
            </CardContent>
          </Card>

          <Button onClick={onSave} disabled={update.isPending} className="w-full">
            {update.isPending ? t('widget.saving') : t('widget.saveConfig')}
          </Button>
        </div>

        {/* Preview + Embed */}
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-sm">{t('widget.embedSnippet')}</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Tabs value={snippetMode} onValueChange={v => setSnippetMode(v as 'embed' | 'console')}>
                <TabsList>
                  <TabsTrigger value="embed">{t('widget.embedTab')}</TabsTrigger>
                  <TabsTrigger value="console">{t('widget.consoleTab')}</TabsTrigger>
                </TabsList>
              </Tabs>
              <p className="text-xs text-fg-muted">
                {snippetMode === 'embed' ? t('widget.embedHint') : t('widget.consoleHint')}
              </p>
              <div className="relative">
                <pre className="bg-gray-900 text-green-400 text-xs p-4 rounded-lg overflow-x-auto whitespace-pre-wrap break-all">
                  {activeSnippet}
                </pre>
                <Button
                  size="icon"
                  variant="ghost"
                  className="absolute top-2 right-2 h-8 w-8"
                  onClick={onCopy}
                >
                  {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                </Button>
              </div>
              <p className="text-xs text-fg-muted">{t('widget.publicKey')}: <code className="bg-surface px-1 rounded">{bot?.public_key ?? '—'}</code></p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-sm">{t('widget.preview')}</CardTitle></CardHeader>
            <CardContent>
              {bot?.public_key ? (
                <div className="relative bg-surface rounded-lg h-96 overflow-hidden border border-line">
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
Página de prueba — el widget aparece abajo a la ${position === 'bottom-right' ? 'derecha' : 'izquierda'}.
</div>
<script
  src="${typeof window !== 'undefined' ? window.location.origin : ''}/widget/widget.js"
  data-public-key="${bot.public_key}"
  data-api-base="${typeof window !== 'undefined' ? window.location.origin : ''}"
  async
></script>
</body></html>`}
                  />
                  <p className="absolute bottom-1 left-2 text-[10px] text-fg-faint">
                    {t('widget.previewNote')}
                  </p>
                </div>
              ) : (
                <p className="text-fg-faint text-sm text-center py-12">
                  {t('widget.previewLoading')}
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}
