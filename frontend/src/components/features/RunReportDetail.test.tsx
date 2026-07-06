import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { RunReportDetail } from '@/components/features/RunReportDetail'
import type { EvalReportJson } from '@/types/api'

// The app defaults to Spanish (src/lib/i18n.ts falls back to "es" when no
// tfm_rag_lang is in localStorage), so assertions below use the ES catalog.

function makeReport(overrides: Partial<EvalReportJson> = {}): EvalReportJson {
  return {
    chatbot_name: 'Mi Chatbot',
    ragas_judge_model: 'gpt-oss-20b',
    generator_model: 'llama-3.3-70b',
    dataset_path: 'world-countries',
    run_started_at: '2026-07-04T10:00:00Z',
    summary: {
      num_cases: 1,
      num_scored: 1,
      num_errors: 0,
      metrics: { answer_correctness: 0.9 },
    },
    cases: [
      {
        question: 'Q1?',
        ground_truth: 'GT',
        scenario: 'docs',
        predicted_answer: 'A',
        scores: { answer_correctness: 0.9 },
        error: null,
        retrieved_contexts: [],
        iterations: [],
      },
    ],
    ...overrides,
  }
}

describe('RunReportDetail metadata header', () => {
  it('renders the generator model and judge model from the report', () => {
    render(<RunReportDetail scenario="docs" report={makeReport()} />)

    expect(screen.getByText('Modelo generador')).toBeInTheDocument()
    expect(screen.getByText('llama-3.3-70b')).toBeInTheDocument()
    expect(screen.getByText('Modelo juez')).toBeInTheDocument()
    expect(screen.getByText('gpt-oss-20b')).toBeInTheDocument()
  })

  it('falls back to "—" when generator and judge models are null/absent', () => {
    render(
      <RunReportDetail
        scenario="docs"
        report={makeReport({ generator_model: null, ragas_judge_model: undefined })}
      />,
    )

    // Both the generator and judge model rows show the em-dash fallback.
    expect(screen.getByText('Modelo generador')).toBeInTheDocument()
    expect(screen.getByText('Modelo juez')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })
})
