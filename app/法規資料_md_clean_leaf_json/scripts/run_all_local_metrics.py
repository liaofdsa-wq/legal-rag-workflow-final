from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET_DIR = ROOT / "evaluation_dataset"
DEFAULT_OUTPUT_ROOT = ROOT / "data" / "evaluation_outputs"
DEFAULT_RESULTS_ROOT = ROOT / "data" / "evaluation_results_batch4"
DEFAULT_OLLAMA_MODEL = "qwen2.5:3b"
DEFAULT_DATASETS = (
    "general_qa_15.xlsx",
    "large_doc_qa.xlsx",
    "table_qa.xlsx",
    "consistency_qa.xlsx",
)


def run_command(command: list[str]) -> None:
    print("Running:", " ".join(str(part) for part in command))
    subprocess.run(command, check=True)


def dataset_stem(file_name: str) -> str:
    return Path(file_name).stem


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run local-copy evaluation outputs and all four metrics for multiple datasets separately."
    )
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--datasets", nargs="+", default=list(DEFAULT_DATASETS))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--mode", default="combined_leaf_table")
    parser.add_argument("--embedding-model", default="BAAI/bge-m3")
    parser.add_argument("--ollama-model", default=DEFAULT_OLLAMA_MODEL)
    parser.add_argument("--ollama-timeout", type=int, default=300)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--prompt-top-n", type=int, default=3)
    parser.add_argument("--max-context-chars", type=int, default=3000)
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--force-rerun", action="store_true")
    args = parser.parse_args()

    eval_script = SCRIPTS_DIR / "run_evaluation_questions - 複製.py"
    metrics_script = SCRIPTS_DIR / "evaluate_all_metrics.py"

    for dataset in args.datasets:
        file_path = args.dataset_dir / dataset
        if not file_path.exists():
            raise FileNotFoundError(f"Missing dataset: {file_path}")

        stem = dataset_stem(dataset)
        output_path = args.output_root / f"eval_outputs_{stem}.jsonl"
        result_dir = args.results_root / stem

        eval_cmd = [
            sys.executable,
            str(eval_script),
            "--dataset-dir",
            str(args.dataset_dir),
            "--input-files",
            dataset,
            "--output",
            str(output_path),
            "--mode",
            args.mode,
            "--embedding-model",
            args.embedding_model,
            "--ollama-model",
            args.ollama_model,
            "--ollama-timeout",
            str(args.ollama_timeout),
            "--top-k",
            str(args.top_k),
            "--prompt-top-n",
            str(args.prompt_top_n),
            "--max-context-chars",
            str(args.max_context_chars),
            "--alpha",
            str(args.alpha),
        ]
        if args.force_rerun:
            eval_cmd.append("--force-rerun")

        metrics_cmd = [
            sys.executable,
            str(metrics_script),
            "--input",
            str(output_path),
            "--output-dir",
            str(result_dir),
            "--ollama-model",
            args.ollama_model,
        ]
        if args.force_rerun:
            metrics_cmd.append("--force-rerun")

        print(f"\n=== Dataset: {dataset} ===")
        run_command(eval_cmd)
        run_command(metrics_cmd)

    print(f"\nDone. Outputs: {args.output_root}")
    print(f"Done. Metric directories: {args.results_root}")


if __name__ == "__main__":
    main()
