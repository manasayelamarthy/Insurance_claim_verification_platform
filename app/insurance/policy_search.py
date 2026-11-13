from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_CHUNK_TOKENS = 500
OVERLAP_TOKENS = 75
STOP_WORDS = {
    "a", "an", "are", "as", "be", "for", "how", "is", "of", "on", "or",
    "the", "to", "what", "which", "with",
}


class PolicySearchError(ValueError):
    """Raised when a policy cannot be indexed or searched."""


@dataclass(frozen=True)
class PolicyChunk:
    page_number: int
    section: str
    text: str
    token_count: int


@dataclass(frozen=True)
class PolicySearchResult:
    page_number: int
    section: str
    text: str
    score: float


@dataclass(frozen=True)
class PolicyAnswer:
    question: str
    answer: str
    citations: tuple[dict[str, object], ...]
    grounded: bool


def chunk_policy(policy_file: Path) -> list[PolicyChunk]:
    """Split a policy at sections and sentence-sized token windows."""
    pages = read_policy_pages(policy_file)
    chunks: list[PolicyChunk] = []

    for page_number, page_text in enumerate(pages, start=1):
        section = "Unsectioned content"
        paragraphs: list[str] = []
        for line in page_text.splitlines():
            line = " ".join(line.split())
            if not line:
                if paragraphs:
                    add_paragraph_chunks(
                        chunks, page_number, section, " ".join(paragraphs)
                    )
                    paragraphs = []
                continue
            if is_heading(line):
                if paragraphs:
                    add_paragraph_chunks(
                        chunks, page_number, section, " ".join(paragraphs)
                    )
                    paragraphs = []
                section = line
            else:
                paragraphs.append(line)
        if paragraphs:
            add_paragraph_chunks(chunks, page_number, section, " ".join(paragraphs))

    if not chunks:
        raise PolicySearchError(f"Policy has no searchable text: {policy_file.name}")
    return chunks


def search_policy(
    policy_file: Path, question: str, limit: int = 3
) -> list[PolicySearchResult]:
    """Retrieve policy chunks using TF-IDF cosine similarity."""
    query_terms = useful_words(question)
    if not query_terms:
        raise PolicySearchError("Search question cannot be empty")

    chunks = chunk_policy(policy_file)
    document_terms = [useful_words(chunk.text) for chunk in chunks]
    document_frequency = Counter(
        term for terms in document_terms for term in set(terms)
    )
    query_vector = tfidf(query_terms, document_frequency, len(chunks))
    results: list[PolicySearchResult] = []

    for chunk, terms in zip(chunks, document_terms):
        score = cosine_similarity(
            query_vector, tfidf(terms, document_frequency, len(chunks))
        )
        if score > 0:
            results.append(
                PolicySearchResult(
                    page_number=chunk.page_number,
                    section=chunk.section,
                    text=chunk.text,
                    score=round(score, 3),
                )
            )

    results.sort(key=lambda result: result.score, reverse=True)
    return results[:limit]


def answer_policy(
    policy_file: Path, question: str, limit: int = 3
) -> PolicyAnswer:
    """Create an auditable answer from retrieved policy clauses.

    This is intentionally extractive until an approved LLM provider is configured.
    No answer is generated when the policy has no matching evidence.
    """
    results = search_policy(policy_file, question, limit)
    citations = tuple(
        {
            "page_number": result.page_number,
            "section": result.section,
            "score": result.score,
        }
        for result in results
    )
    if not results:
        return PolicyAnswer(
            question=question,
            answer="The policy does not contain enough matching information to answer this question.",
            citations=(),
            grounded=False,
        )

    answer = "Based on the following policy clause(s):\n\n" + "\n\n".join(
        f"[Page {result.page_number}; {result.section}] {result.text}"
        for result in results
    )
    return PolicyAnswer(
        question=question,
        answer=answer,
        citations=citations,
        grounded=True,
    )


def read_policy_pages(policy_file: Path) -> list[str]:
    try:
        import pypdf

        reader = pypdf.PdfReader(str(policy_file))
        return [page.extract_text() or "" for page in reader.pages]
    except (OSError, pypdf.errors.PdfReadError) as error:
        raise PolicySearchError(f"Unable to read policy: {policy_file.name}") from error


def add_paragraph_chunks(
    chunks: list[PolicyChunk], page_number: int, section: str, paragraph: str
) -> None:
    tokens = paragraph.split()
    step = MAX_CHUNK_TOKENS - OVERLAP_TOKENS
    for start in range(0, len(tokens), step):
        window = tokens[start : start + MAX_CHUNK_TOKENS]
        text = " ".join(window).strip()
        if text:
            chunks.append(
                PolicyChunk(
                    page_number=page_number,
                    section=section,
                    text=text,
                    token_count=len(window),
                )
            )
        if start + MAX_CHUNK_TOKENS >= len(tokens):
            break


def is_heading(line: str) -> bool:
    if line.lower().startswith(("section ", "chapter ", "part ")):
        return True
    words = line.split()
    return len(words) <= 12 and line == line.upper() and any(char.isalpha() for char in line)


def useful_words(text: str) -> list[str]:
    return [word for word in re.findall(r"[a-z0-9]+", text.lower()) if word not in STOP_WORDS]


def tfidf(
    terms: list[str], document_frequency: Counter[str], document_count: int
) -> dict[str, float]:
    counts = Counter(terms)
    vector: dict[str, float] = {}
    for term, count in counts.items():
        inverse_frequency = math.log((document_count + 1) / (document_frequency[term] + 1)) + 1
        vector[term] = (count / len(terms)) * inverse_frequency
    return vector


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    numerator = sum(value * right.get(term, 0.0) for term, value in left.items())
    left_length = math.sqrt(sum(value * value for value in left.values()))
    right_length = math.sqrt(sum(value * value for value in right.values()))
    return numerator / (left_length * right_length) if left_length and right_length else 0.0


def result_as_dict(result: PolicySearchResult) -> dict[str, object]:
    return asdict(result)
