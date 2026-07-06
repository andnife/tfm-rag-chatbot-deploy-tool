export const SCENARIO_METRICS: Record<string, string[]> = {
  'esc-1': ['faithfulness', 'answer_relevancy', 'context_precision', 'context_recall'],
  'esc-2': ['execution_accuracy', 'answer_relevancy'],
  'esc-3': ['faithfulness', 'answer_relevancy', 'routing_accuracy'],
}

const METRIC_LABELS: Record<string, string> = {
  faithfulness: 'Faithfulness',
  answer_relevancy: 'Answer relevancy',
  context_precision: 'Context precision',
  context_recall: 'Context recall',
  execution_accuracy: 'Execution accuracy',
  routing_accuracy: 'Routing accuracy',
  abstain_accuracy: 'Abstain accuracy',
}

export function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key
}

