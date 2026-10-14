"""Field-level extraction accuracy against the generator's ground truth."""

from __future__ import annotations

from dataclasses import dataclass, field

from credit_agent.schemas import ExtractedField


@dataclass
class FieldScore:
    filename: str
    correct: int = 0
    total: int = 0
    wrong: list[tuple[str, str, str | None]] = field(default_factory=list)  # (field, expected, got)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 1.0


def score_document(
    fields: list[ExtractedField], expected_fields: dict[str, str], filename: str
) -> FieldScore:
    """Compare normalized values against the canonical truth of the scored fields."""
    got = {f.name: f.normalized_value for f in fields}
    score = FieldScore(filename=filename)
    for name, expected in expected_fields.items():
        score.total += 1
        if got.get(name) == expected:
            score.correct += 1
        else:
            score.wrong.append((name, expected, got.get(name)))
    return score


def aggregate_accuracy(scores: list[FieldScore]) -> float:
    total = sum(s.total for s in scores)
    return sum(s.correct for s in scores) / total if total else 1.0
