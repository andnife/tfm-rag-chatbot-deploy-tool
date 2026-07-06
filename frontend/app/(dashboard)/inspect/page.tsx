'use client'

import { useTranslation } from 'react-i18next'
import { AppShell } from '@/components/layout/AppShell'
import { SuperadminGuard } from '@/components/SuperadminGuard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import {
  useChatbots,
  useCredentials,
  useKnowledgeBases,
  useMe,
  useOllamaModels,
} from '@/lib/queries'

function KV({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 text-xs">
      <span className="text-gray-500 min-w-[110px]">{label}</span>
      <span className="font-mono break-all">{value}</span>
    </div>
  )
}

function InspectPageInner() {
  const { t } = useTranslation()
  const me = useMe()
  const creds = useCredentials()
  const kbs = useKnowledgeBases()
  const bots = useChatbots()
  const ollama = useOllamaModels()

  return (
    <AppShell title={t('inspect.title')}>
      <p className="text-gray-500 mb-6 text-sm">
        {t('inspect.subtitle')}
      </p>

      <div className="space-y-6">
        <Card>
          <CardHeader><CardTitle className="text-sm">{t('inspect.accountTenant')}</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {me.isLoading && <p className="text-xs text-gray-500">{t('common.loading')}</p>}
            {me.data && (
              <>
                <KV label="user_id" value={me.data.id} />
                <KV label="email" value={me.data.email} />
                <KV label="tenant_id" value={me.data.tenant_id} />
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t('inspect.credentials')} ({creds.data?.length ?? 0})</CardTitle>
          </CardHeader>
          <CardContent>
            {creds.isLoading && <p className="text-xs text-gray-500">{t('common.loading')}</p>}
            {creds.data && creds.data.length === 0 && (
              <p className="text-xs text-gray-500">{t('inspect.noCredentials')}</p>
            )}
            {creds.data && creds.data.length > 0 && (
              <div className="overflow-x-auto -mx-6 px-6">
              <table className="w-full text-xs min-w-[600px]">
                <thead className="text-left text-gray-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pr-4">ID</th>
                    <th className="py-2 pr-4">Provider</th>
                    <th className="py-2 pr-4">Label</th>
                    <th className="py-2 pr-4">Base URL</th>
                    <th className="py-2">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {creds.data.map(c => (
                    <tr key={c.id} className="border-b border-gray-100 last:border-0">
                      <td className="py-2 pr-4 font-mono">{c.id.slice(0, 8)}</td>
                      <td className="py-2 pr-4">{c.provider_id}</td>
                      <td className="py-2 pr-4">{c.label}</td>
                      <td className="py-2 pr-4 text-gray-500">{c.base_url ?? '—'}</td>
                      <td className="py-2">{c.config_source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t('inspect.kbs')} ({kbs.data?.length ?? 0})</CardTitle>
          </CardHeader>
          <CardContent>
            {kbs.isLoading && <p className="text-xs text-gray-500">{t('common.loading')}</p>}
            {kbs.data && kbs.data.length === 0 && (
              <p className="text-xs text-gray-500">{t('inspect.noKbs')}</p>
            )}
            {kbs.data && kbs.data.length > 0 && (
              <div className="overflow-x-auto -mx-6 px-6">
              <table className="w-full text-xs min-w-[600px]">
                <thead className="text-left text-gray-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pr-4">ID</th>
                    <th className="py-2 pr-4">{t('inspect.colName')}</th>
                    <th className="py-2 pr-4">Embedding</th>
                    <th className="py-2 pr-4">Dim</th>
                    <th className="py-2">{t('inspect.colChunking')}</th>
                  </tr>
                </thead>
                <tbody>
                  {kbs.data.map(kb => (
                    <tr key={kb.id} className="border-b border-gray-100 last:border-0">
                      <td className="py-2 pr-4 font-mono">{kb.id.slice(0, 8)}</td>
                      <td className="py-2 pr-4">{kb.name}</td>
                      <td className="py-2 pr-4">
                        {kb.embedding_selection.model_id}
                      </td>
                      <td className="py-2 pr-4">{kb.embedding_selection.dim}d</td>
                      <td className="py-2">
                        {kb.chunking_config.strategy} · {kb.chunking_config.chunk_size}/
                        {kb.chunking_config.chunk_overlap}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t('inspect.chatbots')} ({bots.data?.length ?? 0})</CardTitle>
          </CardHeader>
          <CardContent>
            {bots.isLoading && <p className="text-xs text-gray-500">{t('common.loading')}</p>}
            {bots.data && bots.data.length === 0 && (
              <p className="text-xs text-gray-500">{t('inspect.noChatbots')}</p>
            )}
            {bots.data && bots.data.length > 0 && (
              <div className="overflow-x-auto -mx-6 px-6">
              <table className="w-full text-xs min-w-[600px]">
                <thead className="text-left text-gray-500 border-b border-gray-200">
                  <tr>
                    <th className="py-2 pr-4">ID</th>
                    <th className="py-2 pr-4">{t('inspect.colName')}</th>
                    <th className="py-2 pr-4">LLM</th>
                    <th className="py-2 pr-4">KBs</th>
                    <th className="py-2">{t('inspect.colPublicKey')}</th>
                  </tr>
                </thead>
                <tbody>
                  {bots.data.map(b => (
                    <tr key={b.id} className="border-b border-gray-100 last:border-0">
                      <td className="py-2 pr-4 font-mono">{b.id.slice(0, 8)}</td>
                      <td className="py-2 pr-4">{b.name}</td>
                      <td className="py-2 pr-4">
                        {b.llm_selection.model_id}
                      </td>
                      <td className="py-2 pr-4">{b.kb_ids.length}</td>
                      <td className="py-2 font-mono text-gray-500">{b.public_key.slice(0, 16)}…</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">
              {t('inspect.ollamaModels')} ({ollama.data?.models.length ?? 0})
            </CardTitle>
          </CardHeader>
          <CardContent>
            {ollama.isLoading && <p className="text-xs text-gray-500">{t('common.loading')}</p>}
            {ollama.isError && (
              <p className="text-xs text-danger">
                {t('inspect.ollamaError')}
              </p>
            )}
            {ollama.data && ollama.data.models.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {ollama.data.models.map(m => (
                  <Badge key={m.name} variant="default" className="font-mono text-[10px]">
                    {m.name} · {(m.size / 1e9).toFixed(1)}GB
                  </Badge>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">{t('inspect.cliTitle')}</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-xs">
            <div>
              <p className="text-gray-500 mb-1">{t('inspect.postgresLabel')}</p>
              <pre className="bg-gray-50 rounded p-2 overflow-x-auto leading-tight">
{`docker exec -it tfm-rag-postgres-1 psql -U tfm -d tfm_rag
\\dt                                   -- listar tablas
SELECT id, email, tenant_id FROM users;
SELECT id, name, embedding_selection FROM knowledge_bases;
SELECT id, ingest_status, kb_id FROM sources;
SELECT id, name, llm_selection FROM chatbots;
SELECT id, status, progress, error FROM ingestion_jobs ORDER BY started_at DESC;`}
              </pre>
            </div>
            <div>
              <p className="text-gray-500 mb-1">{t('inspect.qdrantLabel')}</p>
              <pre className="bg-gray-50 rounded p-2 overflow-x-auto leading-tight">
{`# Ejemplo local — ajusta host/puerto si Qdrant no corre en localhost:6333
curl -s http://localhost:6333/collections | jq

# Para una colección concreta (usa tu tenant_id y dim del embedding):
curl -s http://localhost:6333/collections/kb_chunks__<tenant_id>__1024 | jq
curl -s "http://localhost:6333/collections/kb_chunks__<tenant_id>__1024/points/scroll" \\
  -H 'Content-Type: application/json' -d '{"limit": 5, "with_payload": true}' | jq`}
              </pre>
            </div>
            <div>
              <p className="text-gray-500 mb-1">{t('inspect.storageLabel')}</p>
              <pre className="bg-gray-50 rounded p-2 overflow-x-auto leading-tight">
{`ls -lah /tmp/tfm_rag_storage/
find /tmp/tfm_rag_storage -type f`}
              </pre>
            </div>
          </CardContent>
        </Card>
      </div>
    </AppShell>
  )
}

export default function InspectPage() {
  return (
    <SuperadminGuard>
      <InspectPageInner />
    </SuperadminGuard>
  )
}
