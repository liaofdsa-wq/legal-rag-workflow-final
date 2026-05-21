from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent

GENERAL_ROOT = ROOT / "一般層級" / "法規資料_md_clean_leaf_json" / "data"
SPECIAL_ROOT = ROOT / "表格特殊層" / "08_leaf_json_embedding_問答" / "法規資料_md_clean_leaf_json" / "data"
APP_ROOT = ROOT / "app" / "法規資料_md_clean_leaf_json" / "data"

GENERAL_INPUT_PDF_DIR = ROOT / "一般層級" / "01_原始PDF" / "法規資料"
SPECIAL_INPUT_PDF_DIR = ROOT / "表格特殊層" / "01_原始PDF" / "法規資料"

GENERAL_JSON_ROOT = GENERAL_ROOT / "json"
SPECIAL_JSON_ROOT = SPECIAL_ROOT / "json"
APP_JSON_ROOT = APP_ROOT / "json"

GENERAL_SUMMARY_ROOT = GENERAL_ROOT / "summary"
SPECIAL_SUMMARY_ROOT = SPECIAL_ROOT / "summary"
APP_SUMMARY_ROOT = APP_ROOT / "summary"


def allowed_md_names(pdf_dir: Path) -> set[str]:
    names: set[str] = set()
    for pdf_path in sorted(pdf_dir.glob("*.pdf")) + sorted(pdf_dir.glob("*.PDF")):
        names.add(f"{pdf_path.stem}.json")
    return names


def clean_json_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for json_path in path.glob("*.json"):
        json_path.unlink()


def clean_summary_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for json_path in path.glob("*.json"):
        json_path.unlink()


def copy_filtered_jsons(src_dir: Path, dst_dir: Path, allowed_names: set[str]) -> list[Path]:
    copied: list[Path] = []
    for src_path in sorted(src_dir.glob("*.json")):
        if allowed_names and src_path.name not in allowed_names:
            continue
        dst_path = dst_dir / src_path.name
        shutil.copy2(src_path, dst_path)
        copied.append(dst_path)
    return copied


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def aggregate_list_jsons(paths: list[Path]) -> list[Any]:
    rows: list[Any] = []
    for path in paths:
        payload = read_json(path)
        if isinstance(payload, list):
            rows.extend(payload)
        else:
            rows.append(payload)
    return rows


def load_file_summary(summary_path: Path) -> list[dict[str, Any]]:
    if not summary_path.exists():
        return []
    payload = read_json(summary_path)
    return payload if isinstance(payload, list) else []


def rewrite_summary_paths(entry: dict[str, Any]) -> dict[str, Any]:
    rewritten = dict(entry)
    file_stem = Path(entry["file_name"]).stem
    rewritten["all_node_json"] = str(APP_JSON_ROOT / "all_nodes_per_file" / f"{file_stem}.json")
    rewritten["leaf_json"] = str(APP_JSON_ROOT / "leaf_nodes_per_file" / f"{file_stem}.json")
    rewritten["table_cell_json"] = str(APP_JSON_ROOT / "table_cells_per_file" / f"{file_stem}.json")
    rewritten["table_chunk_json"] = str(APP_JSON_ROOT / "table_chunks_per_file" / f"{file_stem}.json")
    return rewritten


def filter_file_summary_rows(rows: list[dict[str, Any]], allowed_names: set[str]) -> list[dict[str, Any]]:
    allowed_md = {Path(name).stem + ".md" for name in allowed_names}
    return [rewrite_summary_paths(row) for row in rows if row.get("file_name") in allowed_md]


def merge_json_to_app() -> dict[str, Any]:
    general_allowed = allowed_md_names(GENERAL_INPUT_PDF_DIR)
    special_allowed = allowed_md_names(SPECIAL_INPUT_PDF_DIR)

    category_rules = {
        "all_nodes_per_file": [
            (GENERAL_JSON_ROOT / "all_nodes_per_file", general_allowed),
            (SPECIAL_JSON_ROOT / "all_nodes_per_file", special_allowed),
        ],
        "leaf_nodes_per_file": [
            (GENERAL_JSON_ROOT / "leaf_nodes_per_file", general_allowed),
            (SPECIAL_JSON_ROOT / "leaf_nodes_per_file", special_allowed),
        ],
        "table_cells_per_file": [
            (SPECIAL_JSON_ROOT / "table_cells_per_file", special_allowed),
        ],
        "table_chunks_per_file": [
            (SPECIAL_JSON_ROOT / "table_chunks_per_file", special_allowed),
        ],
        "single_tree_per_file": [
            (SPECIAL_JSON_ROOT / "single_tree_per_file", special_allowed),
        ],
        "single_tree_sqlite_per_file": [
            (SPECIAL_JSON_ROOT / "single_tree_sqlite_per_file", special_allowed),
        ],
        "special_nodes_1_per_file": [
            (SPECIAL_JSON_ROOT / "special_nodes_1_per_file", special_allowed),
        ],
    }

    copied_by_category: dict[str, list[Path]] = {}
    for category, sources in category_rules.items():
        dst_dir = APP_JSON_ROOT / category
        clean_json_dir(dst_dir)
        copied_paths: list[Path] = []
        for src_dir, allowed in sources:
            if not src_dir.exists():
                continue
            copied_paths.extend(copy_filtered_jsons(src_dir, dst_dir, allowed))
        copied_by_category[category] = copied_paths

    clean_summary_dir(APP_SUMMARY_ROOT)

    general_summary_rows = filter_file_summary_rows(
        load_file_summary(GENERAL_SUMMARY_ROOT / "file_summary.json"),
        general_allowed,
    )
    special_summary_rows = filter_file_summary_rows(
        load_file_summary(SPECIAL_SUMMARY_ROOT / "file_summary.json"),
        special_allowed,
    )
    merged_file_summary = general_summary_rows + special_summary_rows

    write_json(APP_SUMMARY_ROOT / "file_summary.json", merged_file_summary)
    write_json(
        APP_SUMMARY_ROOT / "all_nodes.json",
        aggregate_list_jsons(copied_by_category["all_nodes_per_file"]),
    )
    write_json(
        APP_SUMMARY_ROOT / "all_leaf_nodes.json",
        aggregate_list_jsons(copied_by_category["leaf_nodes_per_file"]),
    )
    write_json(
        APP_SUMMARY_ROOT / "all_table_cells.json",
        aggregate_list_jsons(copied_by_category["table_cells_per_file"]),
    )
    write_json(
        APP_SUMMARY_ROOT / "all_table_chunks.json",
        aggregate_list_jsons(copied_by_category["table_chunks_per_file"]),
    )
    write_json(
        APP_SUMMARY_ROOT / "all_single_tree.json",
        aggregate_list_jsons(copied_by_category["single_tree_per_file"]),
    )
    write_json(
        APP_SUMMARY_ROOT / "all_special_nodes_1.json",
        aggregate_list_jsons(copied_by_category["special_nodes_1_per_file"]),
    )

    return {
        "general_allowed_count": len(general_allowed),
        "special_allowed_count": len(special_allowed),
        "copied_counts": {key: len(value) for key, value in copied_by_category.items()},
        "summary_file_count": len(list(APP_SUMMARY_ROOT.glob("*.json"))),
    }


def main() -> None:
    result = merge_json_to_app()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
