from __future__ import annotations

import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "法規資料"
GENERAL_INPUT_DIR = ROOT / "一般層級" / "01_原始PDF" / "法規資料"
SPECIAL_INPUT_DIR = ROOT / "表格特殊層" / "01_原始PDF" / "法規資料"
SPECIAL_SEED_DIR = ROOT / "表格特殊層" / "01_原始PDF" / "有表格PDF"
MANIFEST_PATH = ROOT / "source_routing_manifest.json"

PDF_SUFFIXES = {".pdf", ".PDF"}

LEADING_SPLIT_RE = re.compile(r"^p(?P<start>\d+)(?:-(?P<end>\d+))?[^A-Za-z0-9\u4e00-\u9fff]*(?P<base>.+)$")
TRAILING_SPLIT_RE = re.compile(
    r"^(?P<base>.+?)\s+p(?P<start>\d+)(?:-(?P<end>\d+))?(?:\s*(?P<tail>(?:本文|附錄|附件|修正對照表|函)))?$"
)
LEADING_NOISE_RE = re.compile(r"^(?:\([^)]*\)|本文|附錄|附件|所有附件|修正對照表|函|\s)+")
WHITESPACE_RE = re.compile(r"\s+")


def iter_pdfs(path: Path) -> list[Path]:
    return sorted(
        [entry for entry in path.iterdir() if entry.is_file() and entry.suffix in PDF_SUFFIXES],
        key=lambda item: item.name,
    )


def normalize_base_name(file_name: str) -> str:
    stem = WHITESPACE_RE.sub(" ", Path(file_name).stem).strip()

    leading_match = LEADING_SPLIT_RE.match(stem)
    if leading_match:
        base = WHITESPACE_RE.sub(" ", leading_match.group("base")).strip()
        return LEADING_NOISE_RE.sub("", base).strip()

    trailing_match = TRAILING_SPLIT_RE.match(stem)
    if trailing_match:
        return WHITESPACE_RE.sub(" ", trailing_match.group("base")).strip()

    return stem


def load_special_base_names() -> set[str]:
    return {normalize_base_name(path.name) for path in iter_pdfs(SPECIAL_SEED_DIR)}


def resolve_special_base_name(file_name: str, special_base_names: set[str]) -> str:
    normalized = normalize_base_name(file_name)
    if normalized in special_base_names:
        return normalized

    stem = WHITESPACE_RE.sub(" ", Path(file_name).stem).strip()
    candidates = [
        base_name
        for base_name in special_base_names
        if base_name and (base_name in stem or base_name in normalized or normalized in base_name)
    ]
    if not candidates:
        return normalized
    candidates.sort(key=len, reverse=True)
    return candidates[0]


def ensure_clean_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for entry in path.iterdir():
        if entry.is_file() and entry.suffix in PDF_SUFFIXES:
            entry.unlink()


def route_source_pdfs() -> dict[str, object]:
    if not SOURCE_DIR.exists():
        raise FileNotFoundError(f"找不到來源資料夾：{SOURCE_DIR}")
    if not SPECIAL_SEED_DIR.exists():
        raise FileNotFoundError(f"找不到特殊層名單資料夾：{SPECIAL_SEED_DIR}")

    special_base_names = load_special_base_names()
    source_files = iter_pdfs(SOURCE_DIR)

    ensure_clean_dir(GENERAL_INPUT_DIR)
    ensure_clean_dir(SPECIAL_INPUT_DIR)

    routed_files: list[dict[str, str]] = []
    general_count = 0
    special_count = 0

    for pdf_path in source_files:
        base_name = resolve_special_base_name(pdf_path.name, special_base_names)
        is_special = base_name in special_base_names
        destination_dir = SPECIAL_INPUT_DIR if is_special else GENERAL_INPUT_DIR
        destination_path = destination_dir / pdf_path.name
        shutil.copy2(pdf_path, destination_path)

        routed_files.append(
            {
                "file_name": pdf_path.name,
                "normalized_base_name": base_name,
                "layer": "表格特殊層" if is_special else "一般層級",
                "destination": str(destination_path),
            }
        )

        if is_special:
            special_count += 1
        else:
            general_count += 1

    manifest = {
        "source_dir": str(SOURCE_DIR),
        "special_seed_dir": str(SPECIAL_SEED_DIR),
        "general_input_dir": str(GENERAL_INPUT_DIR),
        "special_input_dir": str(SPECIAL_INPUT_DIR),
        "source_file_count": len(source_files),
        "general_file_count": general_count,
        "special_file_count": special_count,
        "files": routed_files,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    manifest = route_source_pdfs()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
