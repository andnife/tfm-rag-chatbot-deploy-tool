'use client'

import Link from 'next/link'
import { Bot, MessageSquare, Pencil, Settings, Trash2, List } from 'lucide-react'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { useDeleteChatbot } from '@/lib/queries'
import type { ChatbotOut } from '@/types/api'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export function ChatbotCard({ bot }: { bot: ChatbotOut }) {
  const { t } = useTranslation()
  const [showDelete, setShowDelete] = useState(false)
  const deleteBot = useDeleteChatbot()

  const handleDelete = async () => {
    await deleteBot.mutateAsync(bot.id)
    setShowDelete(false)
  }

  return (
    <Card className="p-5 h-full flex flex-col">
      <div className="flex items-start gap-3">
        <div className="w-10 h-10 rounded-md bg-primary-50 text-primary-600 flex items-center justify-center">
          <Bot className="h-5 w-5" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold truncate">{bot.name}</h3>
          <p className="text-sm text-gray-500 line-clamp-2 mt-1">{bot.description ?? t('common.noDescription')}</p>
          <div className="text-xs text-gray-500 mt-3">{bot.kb_ids.length} KB(s) · {bot.llm_selection.model_id}</div>
        </div>
      </div>
      <div className="mt-4 flex gap-2">
        <Link href={`/chatbots/${bot.id}/playground`} className="flex-1">
          <Button variant="secondary" className="w-full"><MessageSquare className="h-4 w-4" /> {t('chatbots.test')}</Button>
        </Link>
        <Link href={`/chatbots/${bot.id}/edit`}>
          <Button variant="ghost" size="icon" title={t('chatbots.edit')}><Pencil className="h-4 w-4" /></Button>
        </Link>
        <Link href={`/chatbots/${bot.id}/sessions`}>
          <Button variant="ghost" size="icon" title={t('chatbots.sessions')}><List className="h-4 w-4" /></Button>
        </Link>
        <Link href={`/chatbots/${bot.id}/widget`}>
          <Button variant="ghost" size="icon" title={t('chatbots.widget')}><Settings className="h-4 w-4" /></Button>
        </Link>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setShowDelete(true)}
          title={t('common.delete')}
        >
          <Trash2 className="h-4 w-4 text-red-500" />
        </Button>
      </div>

      <Dialog open={showDelete} onOpenChange={setShowDelete}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('chatbots.deleteTitle')}</DialogTitle>
            <DialogDescription>
              {t('chatbots.deleteDesc', { name: bot.name })}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => setShowDelete(false)}>{t('common.cancel')}</Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteBot.isPending}>
              {deleteBot.isPending ? t('common.deleting') : t('common.delete')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
