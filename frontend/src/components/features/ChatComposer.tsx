import { KeyboardEvent, useState } from 'react'
import { Send } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'

interface Props { onSend: (text: string) => void; disabled?: boolean }

export function ChatComposer({ onSend, disabled }: Props) {
  const { t } = useTranslation()
  const [text, setText] = useState('')

  const submit = () => {
    const trimmed = text.trim()
    if (!trimmed || disabled) return
    onSend(trimmed)
    setText('')
  }

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit() }
  }

  return (
    <div className="flex gap-2 items-end">
      <Textarea
        value={text} onChange={e => setText(e.target.value)} onKeyDown={onKey}
        rows={2} placeholder={t('chat.placeholder')} className="resize-none"
        disabled={disabled}
      />
      <Button onClick={submit} disabled={disabled || !text.trim()} size="icon">
        <Send className="h-4 w-4" />
      </Button>
    </div>
  )
}
