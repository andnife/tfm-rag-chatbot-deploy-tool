'use client'

import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useRegister } from '@/lib/queries'
import { ApiError } from '@/lib/api'

export default function RegisterPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const reg = useRegister()

  const schema = z.object({
    email: z.string().email(t('auth.validEmailRequired')),
    password: z.string().min(8, t('auth.passwordMin')),
    confirm: z.string(),
  }).refine((d) => d.password === d.confirm, {
    message: t('auth.passwordsMismatch'),
    path: ['confirm'],
  })
  type FormData = z.infer<typeof schema>

  const { register, handleSubmit, formState: { errors } } = useForm<FormData>({
    resolver: zodResolver(schema),
  })

  const onSubmit = (data: FormData) => {
    reg.mutate({ email: data.email, password: data.password }, {
      onSuccess: () => {
        router.replace('/dashboard')
      },
      onError: (err) => {
        let msg = t('auth.errorRegister')
        if (err instanceof ApiError) {
          msg = err.status === 409 ? t('auth.errorEmailExists') : err.message
        }
        toast.error(msg)
      },
    })
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-canvas p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>RAG Platform</CardTitle>
          <CardDescription>{t('auth.registerTitle')}</CardDescription>
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
              <Input id="password" type="password" autoComplete="new-password" {...register('password')} />
              {errors.password && <p className="text-xs text-danger">{errors.password.message}</p>}
            </div>
            <div className="space-y-2">
              <Label htmlFor="confirm">{t('auth.confirmPassword')}</Label>
              <Input id="confirm" type="password" autoComplete="new-password" {...register('confirm')} />
              {errors.confirm && <p className="text-xs text-danger">{errors.confirm.message}</p>}
            </div>
            <Button type="submit" className="w-full" disabled={reg.isPending}>
              {reg.isPending ? t('auth.registering') : t('auth.registerButton')}
            </Button>
            <p className="text-sm text-fg-muted text-center">
              {t('auth.hasAccount')}{' '}
              <Link href="/login" className="text-primary-600 hover:underline">
                {t('auth.signIn')}
              </Link>
            </p>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
