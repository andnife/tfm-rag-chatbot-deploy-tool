import { useState } from 'react'
import { Database, TestTube, ShieldCheck } from 'lucide-react'
import { toast } from 'sonner'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogTrigger } from '@/components/ui/dialog'
import { useTestDatabaseConnection, useAttachDatabaseSource } from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { DatabaseDriver, SslMode } from '@/types/api'

interface Props {
  kbId: string
}

export function AddDatabaseSourceDialog({ kbId }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [driver, setDriver] = useState<DatabaseDriver>('postgres')
  const [host, setHost] = useState('localhost')
  const [port, setPort] = useState('5432')
  const [dbName, setDbName] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [sslMode, setSslMode] = useState<SslMode>('disable')
  const [testResult, setTestResult] = useState<{ ok: boolean; error: string | null } | null>(null)

  const testConn = useTestDatabaseConnection(kbId)
  const attachDb = useAttachDatabaseSource(kbId)

  const handleTest = async () => {
    setTestResult(null)
    try {
      const result = await testConn.mutateAsync({
        type: 'database',
        spec: { driver, host, port: Number(port), db_name: dbName, username, password, ssl_mode: sslMode },
      })
      setTestResult({ ok: result.ok, error: result.error })
    } catch (err) {
      setTestResult({ ok: false, error: err instanceof ApiError ? err.message : t('db.testError') })
    }
  }

  const handleAttach = async () => {
    try {
      await attachDb.mutateAsync({
        driver,
        host,
        port: Number(port),
        db_name: dbName,
        username,
        password,
        ssl_mode: sslMode,
      })
      setOpen(false)
      resetForm()
      toast.success(t('db.attached'))
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : t('db.attachError'))
    }
  }

  const resetForm = () => {
    setDriver('postgres')
    setHost('localhost')
    setPort('5432')
    setDbName('')
    setUsername('')
    setPassword('')
    setSslMode('disable')
    setTestResult(null)
  }

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) resetForm() }}>
      <DialogTrigger asChild>
        <Button variant="outline"><Database className="h-4 w-4" /> {t('db.addButton')}</Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t('db.title')}</DialogTitle>
          <DialogDescription>
            {t('db.description')}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-2">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>{t('db.engine')}</Label>
              <Select value={driver} onValueChange={(v) => { setDriver(v as DatabaseDriver); setPort(v === 'mysql' ? '3306' : '5432') }}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="postgres">PostgreSQL</SelectItem>
                  <SelectItem value="mysql">MySQL</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t('db.port')}</Label>
              <Input type="number" value={port} onChange={(e) => setPort(e.target.value)} />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>{t('db.host')}</Label>
            <Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="localhost" />
          </div>

          <div className="space-y-1.5">
            <Label>{t('db.dbName')}</Label>
            <Input value={dbName} onChange={(e) => setDbName(e.target.value)} placeholder={t('db.dbNamePlaceholder')} />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label>{t('db.username')}</Label>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
            <div className="space-y-1.5">
              <Label>{t('db.password')}</Label>
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </div>

          <div className="flex gap-2 rounded-md border border-info/30 bg-info-subtle p-3 text-xs text-info">
            <ShieldCheck className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{t('db.securityNote')}</span>
          </div>

          <div className="space-y-1.5">
            <Label>{t('db.ssl')}</Label>
            <Select value={sslMode} onValueChange={(v) => setSslMode(v as SslMode)}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="disable">{t('db.sslDisabled')}</SelectItem>
                <SelectItem value="require">{t('db.sslRequired')}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {testResult && (
            <div className={`rounded-md border p-3 text-sm ${testResult.ok ? 'border-success/30 bg-success-subtle text-success' : 'border-accent-border bg-accent-subtle text-accent'}`}>
              {testResult.ok ? t('db.testOk') : `${t('db.testError')} ${testResult.error}`}
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            variant="secondary"
            onClick={handleTest}
            disabled={!dbName || !username || testConn.isPending}
          >
            <TestTube className="h-4 w-4" />
            {testConn.isPending ? t('db.testing') : t('db.testButton')}
          </Button>
          <Button
            onClick={handleAttach}
            disabled={!dbName || !username || attachDb.isPending}
          >
            {attachDb.isPending ? t('db.attaching') : t('db.attachButton')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
