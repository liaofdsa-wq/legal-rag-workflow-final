from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from rank_bm25 import BM25Okapi


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_runtime import (  # noqa: E402
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_MODEL,
    build_eval_prompt,
    load_embedding_data,
    load_model,
    prepare_prompt_contexts,
    run_search,
)


DATASET_DIR = ROOT / "evaluation_dataset"
DATASET_FILES = (
    "general_qa_15.xlsx",
    "large_doc_qa.xlsx",
    "table_qa.xlsx",
    "consistency_qa.xlsx",
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
RETRIEVAL_MODE = "leaf_with_ancestors"
HYBRID_TEXT_MODE = "leaf"
TOP_K = 5
PROMPT_TOP_N = 5
MAX_CONTEXT_CHARS = DEFAULT_MAX_CONTEXT_CHARS
SAMPLE_SIZE = 5


def load_question_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for file_name in DATASET_FILES:
        path = DATASET_DIR / file_name
        df = pd.read_excel(path)
        for excel_row_index, row in df.iterrows():
            question = str(row.get("question") or "").strip()
            if not question:
                continue
            rows.append(
                {
                    "dataset_file": file_name,
                    "excel_row_index": int(excel_row_index) + 2,
                    "question_id": str(row.get("question_id") or "").strip() or None,
                    "question_type": str(row.get("question_type") or "").strip() or None,
                    "question": question,
                    "reference_answer": str(row.get("reference_answer") or "").strip() or None,
                }
            )
    return rows


def call_groq(prompt: str, api_key: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    with requests.Session() as session:
        session.trust_env = False
        response = session.post(GROQ_URL, headers=headers, data=body, timeout=120)
        response.raise_for_status()
        data = response.json()

    answer = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    usage = data.get("usage") or {}
    return {
        "answer": str(answer).strip(),
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        },
    }


def tokenize_2gram(text: str) -> list[str]:
    normalized = str(text or "")
    return [normalized[i:i + 2] for i in range(len(normalized) - 1)]


def build_bm25(metadata: list[dict[str, Any]]) -> BM25Okapi:
    corpus = [tokenize_2gram(str(item.get("text", ""))) for item in metadata]
    return BM25Okapi(corpus)


def summarize_result_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": item.get("rank"),
        "doc_type": item.get("doc_type"),
        "file_name": item.get("file_name"),
        "path_text": item.get("path_text"),
        "score": round(float(item.get("score", 0.0) or 0.0), 6),
        "rerank_score": round(float(item.get("rerank_score", 0.0) or 0.0), 6),
        "vector_score": round(float(item.get("vector_score", 0.0) or 0.0), 6),
        "keyword_score": round(float(item.get("keyword_score", 0.0) or 0.0), 6),
    }


def main() -> None:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing GROQ_API_KEY")

    question_rows = load_question_rows()
    total_questions = len(question_rows)
    sample_rows = question_rows[:SAMPLE_SIZE]

    print(f"Loading embeddings: mode={RETRIEVAL_MODE}, hybrid_text_mode={HYBRID_TEXT_MODE}")
    doc_embeddings, metadata, _summary = load_embedding_data(RETRIEVAL_MODE, HYBRID_TEXT_MODE)

    print(f"Loading embedding model: {DEFAULT_MODEL}")
    model = load_model(DEFAULT_MODEL)

    print("Building BM25 index in-memory")
    bm25 = build_bm25(metadata)

    sample_results: list[dict[str, Any]] = []
    usage_prompt_total = 0
    usage_completion_total = 0
    usage_total = 0

    for idx, row in enumerate(sample_rows, start=1):
        question = row["question"]
        print(f"[{idx}/{len(sample_rows)}] {question}")
        retrieved_contexts = run_search(
            question,
            model,
            doc_embeddings,
            metadata,
            bm25,
            TOP_K,
            0.5,
        )
        prompt_contexts, context_chars = prepare_prompt_contexts(
            retrieved_contexts,
            prompt_top_n=PROMPT_TOP_N,
            max_context_chars=MAX_CONTEXT_CHARS,
        )
        prompt = build_eval_prompt(question, prompt_contexts)
        groq_result = call_groq(prompt, api_key=api_key)
        usage = groq_result["usage"]
        usage_prompt_total += usage["prompt_tokens"]
        usage_completion_total += usage["completion_tokens"]
        usage_total += usage["total_tokens"]

        sample_results.append(
            {
                "question_id": row.get("question_id"),
                "dataset_file": row["dataset_file"],
                "excel_row_index": row["excel_row_index"],
                "question_type": row.get("question_type"),
                "question": question,
                "reference_answer": row.get("reference_answer"),
                "retrieval_mode": RETRIEVAL_MODE,
                "hybrid_text_mode": HYBRID_TEXT_MODE,
                "top_k": TOP_K,
                "rrf_k": 60,
                "prompt_top_n": PROMPT_TOP_N,
                "context_chars": context_chars,
                "groq_model": GROQ_MODEL,
                "groq_usage": usage,
                "retrieved_top5": [summarize_result_row(item) for item in retrieved_contexts],
                "generated_answer": groq_result["answer"],
            }
        )

    sample_count = len(sample_results) or 1
    avg_prompt_tokens = usage_prompt_total / sample_count
    avg_completion_tokens = usage_completion_total / sample_count
    avg_total_tokens = usage_total / sample_count
    extrapolated_prompt_tokens = round(avg_prompt_tokens * total_questions)
    extrapolated_completion_tokens = round(avg_completion_tokens * total_questions)
    extrapolated_total_tokens = round(avg_total_tokens * total_questions)

    output = {
        "sample_size": len(sample_results),
        "total_questions_in_dataset": total_questions,
        "sample_usage_totals": {
            "prompt_tokens": usage_prompt_total,
            "completion_tokens": usage_completion_total,
            "total_tokens": usage_total,
        },
        "sample_usage_averages": {
            "prompt_tokens": round(avg_prompt_tokens, 2),
            "completion_tokens": round(avg_completion_tokens, 2),
            "total_tokens": round(avg_total_tokens, 2),
        },
        "extrapolated_usage_totals": {
            "prompt_tokens": extrapolated_prompt_tokens,
            "completion_tokens": extrapolated_completion_tokens,
            "total_tokens": extrapolated_total_tokens,
        },
        "sample_results": sample_results,
    }

    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
