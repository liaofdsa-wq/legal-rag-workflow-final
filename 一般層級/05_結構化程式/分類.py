import csv
import re
import shutil
from pathlib import Path
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# 1. 路徑定義
BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACKAGE_ROOT / "04_Markdown精修區" / "法規資料_md"
RESULT_DIR = PACKAGE_ROOT / "06_CleanTree生成區" / "法規資料_md_clean"
LOG_DIR = RESULT_DIR / "log"

if RESULT_DIR.exists():
    shutil.rmtree(RESULT_DIR)

working_dir = RESULT_DIR / SOURCE_DIR.name
shutil.copytree(SOURCE_DIR, working_dir)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def rewrite_page_markers(working_dir):
    page_pattern = re.compile(r"^\s*##\s*Page\s*(\d+)", re.IGNORECASE)
    for md_file in Path(working_dir).glob("*.md"):
        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = [f"[page {m.group(1)}]" if (m := page_pattern.match(line.strip())) else line for line in lines]
        md_file.write_text("\n".join(new_lines), encoding="utf-8")
    print("[OK] 頁碼已轉換為 [page X]")

def extract_tables():
    def is_table_separator(line: str) -> bool:
        s = line.strip()
        if s.count("|") < 2: return False
        cols = [c.strip() for c in s.split("|") if c.strip()]
        return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cols)

    def is_table_line(line: str) -> bool:
        s = line.strip()
        if not s or (s.startswith("[") and s.endswith("]")): return False
        return s.count("|") >= 2 or is_table_separator(line)

    def process_file(md_path: Path, writer):
        lines = md_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines, table_id, i = [], 0, 0
        while i < len(lines):
            if is_table_line(lines[i]):
                block = []
                while i < len(lines) and is_table_line(lines[i]):
                    block.append(lines[i])
                    i += 1
                if any(is_table_separator(l) for l in block) or len(block) >= 3:
                    table_id += 1
                    table_tag = f"{md_path.stem}_table_{table_id}"
                    subfolder = RESULT_DIR / "tables" / md_path.stem
                    subfolder.mkdir(parents=True, exist_ok=True)
                    (subfolder / f"{table_tag}.md").write_text("\n".join(block), encoding="utf-8")
                    writer.writerow([md_path.name, f"{table_tag}.md", len(block)])
                    new_lines.append(f"[TABLE_REMOVED id={table_tag}]")
                else:
                    new_lines.extend(block)
            else:
                new_lines.append(lines[i])
                i += 1
        return new_lines

    LOG_PATH = LOG_DIR / "table_log.csv"
    with open(LOG_PATH, "w", encoding="utf-8-sig", newline="") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["來源檔案", "表格檔名", "行數"])
        for md_file in working_dir.glob("*.md"):
            new_lines = process_file(md_file, writer)
            md_file.write_text("\n".join(new_lines), encoding="utf-8")
    print("[OK] 表格抽取完成")

def clean_md_garbage_folder(input_dir, output_dir, header_threshold=3):
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    page_regex = re.compile(r"^\s*(第\s*\d+\s*頁|第\s*\d+\s*頁\s*共\s*\d+\s*頁|[-–—]?\s*\d+\s*[-–—]?)\s*$", re.I)
    noise_regex = re.compile(r"^\s*\d+\s*$|\d{2,3}年\d{1,2}月.*臺灣期貨交易所")

    for file in input_dir.glob("*.md"):
        lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        temp_lines = [l for l in lines if l.strip() and not page_regex.match(l.strip()) and not noise_regex.match(l.strip())]
        stripped = [l.strip() for l in temp_lines if not l.strip().startswith("[")]
        counter = Counter(stripped)
        headers = {line for line, count in counter.items() if count >= header_threshold and len(line) <= 30}
        final_lines = [l for l in temp_lines if l.strip().startswith("[") or l.strip() not in headers]
        (output_dir / file.name).write_text("\n".join(final_lines), encoding="utf-8")
    print("[OK] 垃圾清理完成")

# 🔥 核心修正：僅保留標籤的 Heading 解析器
def extract_heading_lines():
    import re
    OUT_DIR = RESULT_DIR / "headings"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURE_DIR = RESULT_DIR / "structure"
    STRUCTURE_DIR.mkdir(parents=True, exist_ok=True)

    # 定義標籤類型與權重
    TAG_WEIGHT = {
        "CHAPTER": 0, "SECTION": 1, "ARTICLE": 2, "PARAGRAPH": 3, "SUBITEM": 4,
        "ITEM_ZH_BIG": 5, "PAREN_ZH_BIG": 6,
        "ITEM_ZH": 7,     "PAREN_ZH": 8,
        "POINT_NUM": 9,   "PAREN_NUM": 10,
        "GAN_DOT": 11,    "GAN_PAREN": 12,
        "ALPHA": 13,      "ROMAN": 14
    }

    patterns = [
        ("CHAPTER",     re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*章")),
        ("SECTION",     re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*節")),
        ("ARTICLE",     re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*條")),
        ("PARAGRAPH",   re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*項")),
        ("SUBITEM",     re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*款")),
        ("ITEM_ZH_BIG", re.compile(r"^([壹貳參肆伍陸柒捌玖拾]+)[、．.]")),
        ("PAREN_ZH_BIG",re.compile(r"^[（(]([壹貳參肆伍陸柒捌玖拾]+)[）)]")),
        ("ITEM_ZH",     re.compile(r"^([一二三四五六七八九十]+)[、．.]")),
        ("PAREN_ZH",    re.compile(r"^[（(]([一二三四五六七八九十]+)[）)]")),
        ("POINT_NUM",   re.compile(r"^(\d+)[\.．、]")),
        ("PAREN_NUM",   re.compile(r"^[（(](\d+)[）)]")),
    ]

    for md_file in working_dir.glob("*.md"):
        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines, struct_lines = [], []
        stack = []

        for line in lines:
            s = line.strip()
            matched = False
            for name, pat in patterns:
                if m := pat.match(s):
                    # 獲取標籤內容（例如：第 一 章、一、、(一)）
                    tag_content = m.group(0)
                    current_weight = TAG_WEIGHT[name]
                    
                    # 彈出權重較大的項目（回溯邏輯）
                    while stack and TAG_WEIGHT[stack[-1]['type']] >= current_weight:
                        stack.pop()
                    
                    level = len(stack)
                    stack.append({"type": name, "weight": current_weight})
                    
                    # 輸出格式：僅保留 [標籤]
                    formatted_tag = f"[{tag_content}]"
                    indent = "  " * level
                    
                    new_lines.append(f"{indent}{formatted_tag}")
                    struct_lines.append(f"{indent}{formatted_tag}")
                    matched = True
                    break
            
            # 如果不是標籤行，在此處不加入 new_lines，即可達成「移除後面文字」的效果
            # 只有當 matched 為 True 時才會寫入
            
        md_file.write_text("\n".join(new_lines), encoding="utf-8")
        (STRUCTURE_DIR / md_file.name).write_text("\n".join(struct_lines), encoding="utf-8")
        
    print("[OK] Heading 解析：純標籤 Tree 已生成")

def build_tree_pipeline():
    input_dir = RESULT_DIR / "structure"
    output_dir = RESULT_DIR / "tree"
    output_dir.mkdir(parents=True, exist_ok=True)
    for file_path in input_dir.glob("*.md"):
        shutil.copy(file_path, output_dir / file_path.name)
    print(f"[OK] Tree 輸出完成")

if __name__ == "__main__":
    rewrite_page_markers(working_dir)
    extract_tables()
    clean_md_garbage_folder(working_dir, working_dir)
    extract_heading_lines()
    build_tree_pipeline()