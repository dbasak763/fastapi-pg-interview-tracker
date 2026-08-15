"""Canonical dashboard topics derived from raw interview labels.

Imported attempts preserve the source ``topic`` and ``focus_topic`` verbatim.
Those fields are often much more specific than a useful dashboard selector, so
this module provides a stable read-time category without rewriting source data.
"""

import re
from typing import Optional


TOPIC_CATEGORIES = (
    "Algorithms & Data Structures",
    "Behavioral & Communication",
    "Programming & Code Quality",
    "Computer Vision",
    "Data & Feature Platforms",
    "Deep Learning",
    "Machine Learning Fundamentals",
    "ML Systems & Architecture",
    "Model Evaluation & Operations",
    "Natural Language Processing",
    "Recommendation & Search",
    "Other",
)


CATEGORY_PHRASES = (
    (
        "Behavioral & Communication",
        (
            "communication skills",
            "motivation alignment",
            "motivation and fit",
            "resume professional background",
            "resume and professional background",
            "recruiter screen",
            "conflict collaboration",
            "working style",
        ),
    ),
    (
        "Programming & Code Quality",
        (
            "code quality",
            "readability and maintainability",
            "platform familiarity",
            "resource utilization and documentation",
        ),
    ),
    (
        "Recommendation & Search",
        (
            "recommendation",
            "skip prediction",
            "search ranking",
            "learning to rank",
            "visual search",
            "embedding based",
        ),
    ),
    (
        "Computer Vision",
        (
            "computer vision",
            "defect detection",
        ),
    ),
    (
        "Natural Language Processing",
        (
            "natural language processing",
            "nlp model",
            "tokenization",
        ),
    ),
    (
        "Deep Learning",
        (
            "deep learning",
            "neural network",
            "cnn architecture",
            "backpropagation",
            "gradient descent",
            "activation function",
            "transformer architecture",
            "attention",
            "distributed training stability",
            "optimizer diagnostics",
            "training optimization",
        ),
    ),
    (
        "Data & Feature Platforms",
        (
            "data pipeline",
            "feature platform",
        ),
    ),
    (
        "Model Evaluation & Operations",
        (
            "model evaluation",
            "model monitoring",
            "observability",
            "production metrics",
            "calibration",
            "business guardrail",
            "delayed labels",
            "model deployment",
            "inference optimization",
        ),
    ),
    (
        "ML Systems & Architecture",
        (
            "end to end ml system",
            "machine learning system",
            "ml system design",
            "ml lifecycle",
            "ml system architecture",
            "distributed systems for ml",
            "scalability performance thinking",
            "scalability and performance thinking",
            "serving architecture",
        ),
    ),
    (
        "Machine Learning Fundamentals",
        (
            "machine learning",
            "ml fundamentals",
            "applied ai ml",
            "ai machine learning background",
            "bias variance",
            "regularization",
            "loss function",
            "model architecture selection",
            "pattern recognition",
            "pretrained models",
            "transfer learning",
            "supervised vs unsupervised",
            "classification vs regression",
            "model selection",
        ),
    ),
    (
        "Algorithms & Data Structures",
        (
            "algorithm",
            "recursion",
            "graph",
            "dynamic programming",
            "greedy",
            "interval",
            "heap",
            "tree",
            "trie",
            "complexity",
            "problem breakdown",
            "requirements clarification",
            "iterative solution",
            "problem decomposition",
        ),
    ),
)


def _normalize(value: Optional[str]) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").casefold()))


def canonical_topic(topic: Optional[str], focus_topic: Optional[str] = None) -> str:
    """Return the stable dashboard category for one imported attempt."""

    searchable = f"{_normalize(topic)} {_normalize(focus_topic)}".strip()
    for category, phrases in CATEGORY_PHRASES:
        if any(phrase in searchable for phrase in phrases):
            return category
    return "Other"
