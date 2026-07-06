'use client'

import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import Link from 'next/link'
import Script from 'next/script'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useLogin } from '@/lib/queries'
import { apiJson, ApiError } from '@/lib/api'

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: { client_id: string; callback: (r: { credential: string }) => void }) => void
          renderButton: (el: HTMLElement, opts: { theme?: string; size?: string; width?: number }) => void
        }
      }
    }
  }
}

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const login = useLogin()

  const schema = z.object({
    email: z.string().email(t('auth.validEmailRequired')),
    password: z.string().min(1, t('auth.passwordRequired')),
  })
  type FormData = z.infer<typeof schema>

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID
  const [gisReady, setGisReady] = useState(false)

  useEffect(() => {
    if (!clientId || !gisReady || typeof window === 'undefined' || !window.google) return
    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: async (response: { credential: string }) => {
        try {
          await apiJson('/auth/login/google', 'POST', { google_id_token: response.credential })
          router.replace('/dashboard')
        } catch (err) {
          toast.error(err instanceof ApiError ? err.message : t('auth.errorLoginGoogle'))
        }
      },
    })
    const el = document.getElementById('gis-button')
    if (el) window.google.accounts.id.renderButton(el, { theme: 'outline', size: 'large', width: 360 })
  }, [router, clientId, gisReady, t])

  const onSubmit = (data: FormData) => {
    login.mutate(data, {
      onSuccess: () => {
        router.replace('/dashboard')
      },
      onError: (err) => {
        const msg = err instanceof ApiError ? err.message : t('auth.errorLogin')
        toast.error(msg)
      },
    })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>RAG Platform</CardTitle>
          <CardDescription>{t('auth.loginTitle')}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" {...register('email')} />
              {errors.email && <p className="text-xs text-danger">{errors.email.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">{t('auth.password')}</Label>
              <Input id="password" type="password" autoComplete="current-password" {...register('password')} />
              {errors.password && <p className="text-xs text-danger">{errors.password.message}</p>}
            </div>
            <Button type="submit" className="w-full" disabled={login.isPending}>
              {login.isPending ? t('auth.loggingIn') : t('auth.loginButton')}
            </Button>
          </form>

          {clientId && (
            <>
              <div className="relative my-4">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-line" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="bg-canvas px-2 text-fg-faint">o</span>
                </div>
              </div>

              <Script
                src="https://accounts.google.com/gsi/client"
                strategy="afterInteractive"
                onLoad={() => setGisReady(true)}
              />
              <div id="gis-button" className="flex justify-center" />
            </>
          )}

          <p className="text-sm text-fg-muted text-center mt-4">
            {t('auth.noAccount')}{' '}
            <Link href="/register" className="text-primary-600 hover:underline">
              {t('auth.createAccount')}
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
