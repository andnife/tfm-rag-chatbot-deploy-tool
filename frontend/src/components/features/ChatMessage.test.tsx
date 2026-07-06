import { describe, it, expect } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ChatMessage } from '@/components/features/ChatMessage'
import type { Citation } from '@/types/api'

// The app defaults to Spanish (src/lib/i18n.ts falls back to "es" when no
// tfm_rag_lang is in localStorage), so assertions below use the ES catalog.

const CITATIONS: Citation[] = [
  {
    chunk_id: 'chunk-1',
    source_id: 'doc-1',
    source_name: 'manual.pdf',
    location: 'p. 3',
    score: 0.87,
    preview: 'Excerpt from the manual explaining the widget setup.',
  },
  {
    chunk_id: 'chunk-2',
    source_id: 'doc-2',
    source_name: 'faq.md',
    location: '',
    score: 0.42,
    // No preview — should render as non-expandable.
  },
]

describe('ChatMessage citations', () => {
  it('renders no sources section for a user message', () => {
    render(<ChatMessage role="user" content="What is the refund policy?" />)
    expect(screen.queryByText('Fuentes')).not.toBeInTheDocument()
  })

  it('renders no sources section for an assistant message without citations', () => {
    render(<ChatMessage role="assistant" content="I do not know." />)
    expect(screen.queryByText('Fuentes')).not.toBeInTheDocument()
  })

  it('renders a numbered source list with name, location and score for an assistant message', () => {
    render(<ChatMessage role="assistant" content="Here is the answer." citations={CITATIONS} />)

    expect(screen.getByText('Fuentes')).toBeInTheDocument()
    expect(screen.getByText('[1]')).toBeInTheDocument()
    expect(screen.getByText('[2]')).toBeInTheDocument()
    expect(screen.getByText('manual.pdf')).toBeInTheDocument()
    expect(screen.getByText('faq.md')).toBeInTheDocument()
    expect(screen.getByText(/87%/)).toBeInTheDocument()
    expect(screen.getByText(/42%/)).toBeInTheDocument()
  })

  it('expands a citation with a preview on click to reveal the chunk text, and can collapse it again', () => {
    render(<ChatMessage role="assistant" content="Here is the answer." citations={CITATIONS} />)

    const preview = 'Excerpt from the manual explaining the widget setup.'
    expect(screen.queryByText(preview)).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('manual.pdf'))
    expect(screen.getByText(preview)).toBeInTheDocument()

    fireEvent.click(screen.getByText('manual.pdf'))
    expect(screen.queryByText(preview)).not.toBeInTheDocument()
  })

  it('does not let a preview-less citation be toggled open', () => {
    render(<ChatMessage role="assistant" content="Here is the answer." citations={CITATIONS} />)

    const faqButton = screen.getByText('faq.md').closest('button')
    expect(faqButton).toBeDisabled()
  })
})
