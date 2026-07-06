'use client'

import Link from 'next/link'
import { Database, Trash2 } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useDeleteKnowledgeBase } from '@/lib/queries'
import type { KnowledgeBaseOut } from '@/types/api'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export function KBCard({ kb }: { kb: KnowledgeBaseOut }) {
  const { t } = useTranslation()
  const [showDelete, setShowDelete] = useState(false)
  const deleteKb = useDeleteKnowledgeBase()

  const handleDelete = async () => {
    await deleteKb.mutateAsync(kb.id)
    setShowDelete(false)
  }

  return (
    <Card className="p-5 hover:shadow-md transition-shadow h-full">
      <Link href={`/knowledge/${kb.id}`}>
        <div className="flex items-start gap-3 cursor-pointer">
          <div className="w-10 h-10 rounded-md bg-primary-50 text-primary-600 flex items-center justify-center">
            <Database className="h-5 w-5" />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="font-semibold truncate">{kb.name}</h3>
            <p className="text-sm text-gray-500 line-clamp-2 mt-1">{kb.description ?? t('common.noDescription')}</p>
            <div className="flex gap-3 text-xs text-gray-500 mt-3">
              <span>{kb.embedding_selection.model_id}</span>
              <span>•</span>
              <span>{kb.embedding_selection.dim}d</span>
            </div>
          </div>
        </div>
      </Link>
      <div className="mt-3 flex justify-end">
        <Button
          variant="ghost"
          size="icon"
          onClick={(e) => { e.stopPropagation(); setShowDelete(true) }}
          title={t('common.delete')}
        >
          <Trash2 className="h-4 w-4 text-red-500" />
        </Button>
      </div>

      <Dialog open={showDelete} onOpenChange={setShowDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('kb.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('chatbots.deleteDesc', { name: kb.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setShowDelete(false)}>{t('common.cancel')}</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteKb.isPending}>
              {deleteKb.isPending ? t('common.deleting') : t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
