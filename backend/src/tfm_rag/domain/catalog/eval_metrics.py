"""Metric-name constants for the evaluation report.

These are the column names the RAGAS adapter emits and the report writer /
stats read. They are pure domain vocabulary (strings), so they live in the
domain and are imported by both `application/evaluation` (report writer) and
the RAGAS adapter in `infrastructure/evaluation`.
"""


class RagasMetric:
    """String constants matching the evaluation result frame's column names.

    ``ABSTAIN_ACCURACY`` and ``ROUTING_ACCURACY`` are ours (deterministic),
    not RAGAS's — see the RAGAS adapter for how they are computed.
    """

    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"
    ABSTAIN_ACCURACY = "abstain_accuracy"
    ROUTING_ACCURACY = "routing_accuracy"
