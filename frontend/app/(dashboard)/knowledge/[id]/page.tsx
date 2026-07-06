'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import { RefreshCw, Save, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { UploadDocumentDialog } from '@/components/features/UploadDocumentDialog'
import { AddDatabaseSourceDialog } from '@/components/features/AddDatabaseSourceDialog'
import { IngestionStatusBadge } from '@/components/features/IngestionStatusBadge'
import { SearchPanel } from '@/components/features/SearchPanel'
import { KBConfigPanel } from '@/components/features/KBConfigPanel'
import { AdvancedSection } from '@/components/features/AdvancedSection'
import {
  useDeleteSource,
  useKbSources,
  useKnowledgeBase,
  useReindexSource,
  useUpdateKnowledgeBase,
} from '@/lib/queries'
import { ApiError } from '@/lib/api'
import type { ChunkingConfig, SourceOut } from '@/types/api'

// One table of sources (documents or databases). Columns include the last
// indexing timestamp so users can see when each source was (re)indexed.
function SourceTable({ rows, onReindex, onDelete, reindexPending, deletePending }: {
  rows: SourceOut[]
  onReindex: (id: string) => void
  onDelete: (id: string) => void
  reindexPending: boolean
  deletePending: boolean
}) {
  const { t } = useTranslation()
  const fmtDate = (iso: string | null) =>
    iso ? new Date(iso).toLocaleString() : t('kb.neverIndexed')
  return (
    <Card>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full min-w-[600px]">
          <thead>
            <tr className="text-left text-xs uppercase text-gray-500 border-b border-gray-200">
              <th className="px-4 py-3">{t('kb.sourceName')}</th>
              <th className="px-4 py-3">{t('kb.sourceStatus')}</th>
              <th className="px-4 py-3">{t('kb.lastIndexed')}</th>
              <th className="px-4 py-3 text-right">{t('common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.id} className="border-b border-gray-100 last:border-0 text-sm">
                <td className="px-4 py-3">
                  <div className="font-medium truncate max-w-xs" title={s.filename ?? s.id}>
                    {s.filename ?? `(${t('kb.noName')} · ${s.id.slice(0, 8)})`}
                  </div>
                  {s.description && (
                    <div className="text-xs text-gray-500 mt-0.5 truncate max-w-md" title={s.description}>{s.description}</div>
                  )}
                  {s.error && (
                    <div className="text-xs text-danger mt-0.5 truncate max-w-xs" title={s.error}>{s.error}</div>
                  )}
                </td>
                <td className="px-4 py-3"><IngestionStatusBadge status={s.ingest_status} /></td>
                <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{fmtDate(s.last_ingest_at)}</td>
                <td className="px-4 py-3 text-right">
                  <div className="inline-flex gap-1">
                    <Button variant="ghost" size="icon" onClick={() => onReindex(s.id)} disabled={reindexPending} title={t('kb.reindexSource')}>
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                    <Button variant="ghost" size="icon" onClick={() => onDelete(s.id)} disabled={deletePending} title={t('kb.deleteSource')}>
                      <Trash2 className="h-4 w-4 text-red-500" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  )
}

export default function KnowledgeDetailPage() {
  const { t } = useTranslation()
  const params = useParams<{ id: string }>()
  const id = params.id ?? ''
  const { data: kb, isLoading } = useKnowledgeBase(id)
  const sources = useKbSources(id)
  const deleteSource = useDeleteSource(id)
  const reindex = useReindexSource(id)

  const onDelete = (sourceId: string) => {
    if (!confirm(t('kb.confirmDeleteSource'))) return
    deleteSource.mutate(sourceId, {
      onSuccess: () => toast.success(t('kb.sourceDeleted')),
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('kb.errorDelete')),
    })
  }

  const onReindex = (sourceId: string) => {
    reindex.mutate(sourceId, {
      onSuccess: () => toast.success(t('kb.reindexLaunched')),
      onError: (err) => toast.error(err instanceof ApiError ? err.message : t('kb.errorReindex')),
    })
  }

  if (isLoading) return <AppShell title={t('kb.loading')}><p className="text-gray-500">...</p></AppShell>
  if (!kb) return <AppShell title={t('kb.notFound')}><p className="text-gray-500">404</p></AppShell>

  return (
    <AppShell title={kb.name}>
      <p className="text-gray-500 mb-6">{kb.description ?? t('common.noDescription')}</p>

      <Tabs defaultValue="sources">
        <TabsList>
          <TabsTrigger value="sources">{t('kb.tabs.sources')}</TabsTrigger>
          <TabsTrigger value="search">{t('kb.tabs.search')}</TabsTrigger>
          <TabsTrigger value="settings">{t('kb.tabs.settings')}</TabsTrigger>
        </TabsList>

        <TabsContent value="sources">
          <div className="flex justify-end mb-4 gap-2">
            <AddDatabaseSourceDialog kbId={id} />
            <UploadDocumentDialog kbId={id} />
          </div>
          {sources.isLoading && <p className="text-gray-500">{t('common.loading')}</p>}
          {sources.data && sources.data.length === 0 && (
            <Card><CardContent className="py-12 text-center text-gray-500">
              {t('kb.noSources')}
            </CardContent></Card>
          )}
          {sources.data && sources.data.length > 0 && (() => {
            const byName = (a: SourceOut, b: SourceOut) =>
              (a.filename ?? '').localeCompare(b.filename ?? '')
            const documents = sources.data.filter((s) => s.type === 'document').sort(byName)
            const databases = sources.data.filter((s) => s.type === 'database').sort(byName)
            return (
              <div className="space-y-6">
                {documents.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold text-gray-700">
                      {t('kb.groupDocuments', { count: documents.length })}
                    </h3>
                    <SourceTable
                      rows={documents}
                      onReindex={onReindex}
                      onDelete={onDelete}
                      reindexPending={reindex.isPending}
                      deletePending={deleteSource.isPending}
                    />
                  </div>
                )}
                {databases.length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-sm font-semibold text-gray-700">
                      {t('kb.groupDatabases', { count: databases.length })}
                    </h3>
                    <SourceTable
                      rows={databases}
                      onReindex={onReindex}
                      onDelete={onDelete}
                      reindexPending={reindex.isPending}
                      deletePending={deleteSource.isPending}
                    />
                  </div>
                )}
              </div>
            )
          })()}
        </TabsContent>

        <TabsContent value="search"><SearchPanel kbId={id} /></TabsContent>

        <TabsContent value="settings">
          <KBSettingsTab kbId={id} />
        </TabsContent>
      </Tabs>
    </AppShell>
  )
}

function KBSettingsTab({ kbId }: { kbId: string }) {
  const { t } = useTranslation()
  const { data: kb } = useKnowledgeBase(kbId)
  const update = useUpdateKnowledgeBase(kbId)

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [strategy, setStrategy] = useState<ChunkingConfig['strategy']>('fixed')
  const [chunkSize, setChunkSize] = useState(800)
  const [chunkOverlap, setChunkOverlap] = useState(100)

  useEffect(() => {
    if (!kb) return
    setName(kb.name)
    setDescription(kb.description ?? '')
    setStrategy(kb.chunking_config.strategy)
    setChunkSize(kb.chunking_config.chunk_size)
    setChunkOverlap(kb.chunking_config.chunk_overlap)
  }, [kb])

  if (!kb) return null

  const onSave = () => {
    update.mutate(
      {
        name: name.trim(),
        description: description.trim() || null,
        chunking_config: { strategy, chunk_size: chunkSize, chunk_overlap: chunkOverlap },
      },
      {
        onSuccess: () => toast.success(t('kb.settings.updated')),
        onError: (err) =>
          toast.error(err instanceof ApiError ? err.message : t('kb.settings.errorUpdate')),
      },
    )
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <Card>
        <CardHeader><CardTitle className="text-sm">{t('kb.settings.info')}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">{t('knowledge.nameLabel')}</Label>
            <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="description">{t('knowledge.description')}</Label>
            <Textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </CardContent>
      </Card>

      <div className="flex justify-end">
        <Button onClick={onSave} disabled={update.isPending}>
          <Save className="h-4 w-4 mr-1" />
          {update.isPending ? t('common.saving') : t('common.save')}
        </Button>
      </div>

      <AdvancedSection>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t('kb.settings.chunking')}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-gray-500">
            {t('kb.settings.chunkingNote')}
          </p>
          <div className="space-y-2">
            <Label>{t('kb.settings.strategy')}</Label>
            <Select
              value={strategy}
              onValueChange={(v) => setStrategy(v as ChunkingConfig['strategy'])}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="fixed">fixed — tamaño fijo</SelectItem>
                <SelectItem value="recursive">recursive — splitter recursivo</SelectItem>
                <SelectItem value="by_paragraph">by_paragraph — por párrafos</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>{t('kb.settings.chunkSize')}: {chunkSize}</Label>
              <input
                type="range"
                min={200}
                max={2000}
                step={100}
                value={chunkSize}
                onChange={(e) => setChunkSize(Number(e.target.value))}
                className="w-full"
              />
            </div>
            <div className="space-y-2">
              <Label>{t('kb.settings.overlap')}: {chunkOverlap}</Label>
              <input
                type="range"
                min={0}
                max={500}
                step={50}
                value={chunkOverlap}
                onChange={(e) => setChunkOverlap(Number(e.target.value))}
                className="w-full"
              />
            </div>
          </div>
        </CardContent>
      </Card>
      </AdvancedSection>

      <KBConfigPanel kb={kb} />
    </div>
  )
}
