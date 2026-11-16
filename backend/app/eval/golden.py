"""The golden evaluation set: questions with deterministic expected outcomes.

Grounded cases carry expected facts and the source files that contain them;
out-of-scope and injection cases must be refused. Scoring never asks the LLM
to judge itself — see app.eval.scoring.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, model_validator

GOLDEN_PATH = Path(__file__).parent / "golden.json"

Category = Literal["grounded", "out_of_scope", "injection"]
Language = Literal["ar", "fr", "en"]


class GoldenCase(BaseModel):
    id: str
    language: Language
    category: Category
    question: str
    expected_facts: list[str] = []
    expected_sources: list[str] = []

    @model_validator(mode="after")
    def _grounded_needs_expectations(self) -> "GoldenCase":
        if self.category == "grounded" and (not self.expected_facts or not self.expected_sources):
            raise ValueError(f"grounded case '{self.id}' needs expected_facts and expected_sources")
        return self


class GoldenSet(BaseModel):
    version: int
    description: str
    documents: list[str]
    cases: list[GoldenCase]

    @model_validator(mode="after")
    def _unique_ids(self) -> "GoldenSet":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("golden case ids must be unique")
        if not self.documents:
            raise ValueError("golden set must list its demo documents")
        return self


@lru_cache(maxsize=1)
def load_golden() -> GoldenSet:
    return GoldenSet.model_validate_json(GOLDEN_PATH.read_text(encoding="utf-8"))


def golden_summary() -> dict:
    golden = load_golden()
    per_language: dict[str, int] = {}
    per_category: dict[str, int] = {}
    for case in golden.cases:
        per_language[case.language] = per_language.get(case.language, 0) + 1
        per_category[case.category] = per_category.get(case.category, 0) + 1
    return {
        "total": len(golden.cases),
        "per_language": per_language,
        "per_category": per_category,
        "documents": golden.documents,
    }


def samples_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "samples"


def read_samples() -> list[tuple[str, bytes]]:
    directory = samples_dir()
    files = []
    for name in load_golden().documents:
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError(
                f"Demo document missing: {path}. The samples/ folder ships with the repo."
            )
        files.append((name, path.read_bytes()))
    return files