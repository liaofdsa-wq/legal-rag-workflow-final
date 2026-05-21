import csv
import re
import shutil
from pathlib import Path
from collections import Counter
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# Codex 副本：
# 1. 不覆蓋原始「結構化法規程式/分類前處理.py」
# 2. build_tree_pipeline 輸出到 tree，供後續 leaf JSON 建置使用

# 1. 路徑定義 (保持你提供的結構)
BASE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACKAGE_ROOT / "04_Markdown精修區" / "法規資料_md"
RESULT_DIR = PACKAGE_ROOT / "06_CleanTree生成區" / "法規資料_md_clean"
LOG_DIR = RESULT_DIR / "log"

if RESULT_DIR.exists():
    shutil.rmtree(RESULT_DIR)

# copy 成子資料夾
working_dir = RESULT_DIR / SOURCE_DIR.name


shutil.copytree(SOURCE_DIR, working_dir)

LOG_DIR.mkdir(parents=True, exist_ok=True)

# 用 working_dir 當主資料夾

def rewrite_page_markers(working_dir):
    import re
    from pathlib import Path

    page_pattern = re.compile(r"^\s*##\s*Page\s*(\d+)", re.IGNORECASE)

    for md_file in Path(working_dir).glob("*.md"):

        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = []

        for line in lines:
            stripped = line.strip()

            m = page_pattern.match(stripped)
            if m:
                page_num = m.group(1)
                new_lines.append(f"[page {page_num}]")  # 👉 替換
            else:
                new_lines.append(line)

        # 👉 覆寫原檔
        md_file.write_text("\n".join(new_lines), encoding="utf-8")

    print("[OK] 頁碼已轉換為 [page X]")
def extract_tables():
    """
    母函式：
    - 從 md 抓出表格區塊
    - 原文移除並加標記
    - 表格另存
    - 紀錄 log
    """

    # ========= 1. 判斷是否為表格行 =========
    def is_table_line(line: str):
        line = line.strip()

        # Markdown 表格 or 分隔線
        if "|" in line:
            return True
        if re.match(r"^\s*\|?[-: ]+\|[-|: ]+\|?\s*$", line):
            return True

        return False

    # ========= 2. 抓表格區塊 =========
    def extract_table_blocks(lines):
        blocks = []
        current_block = []
        in_table = False

        for line in lines:
            if is_table_line(line):
                current_block.append(line)
                in_table = True
            else:
                if in_table:
                    blocks.append(current_block)
                    current_block = []
                    in_table = False

        # 收尾
        if current_block:
            blocks.append(current_block)

        return blocks

    # ========= 3. 單檔處理 =========
    def process_file(md_path: Path, writer):
        with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        table_blocks = extract_table_blocks(lines)

        new_lines = []
        table_id = 0
        i = 0

        while i < len(lines):
            if is_table_line(lines[i]):
                # 收集整塊表格
                block = []
                while i < len(lines) and is_table_line(lines[i]):
                    block.append(lines[i])
                    i += 1

                table_id += 1
                table_tag = f"{md_path.stem}_table_{table_id}"
                table_name = f"{table_tag}.md"
                table_path = RESULT_DIR / "tables"
                table_path.mkdir(exist_ok=True)

                # 假設 table_path 是總資料夾
                table_root = Path(table_path)

                # 👉 用 md 檔名當子資料夾名稱（你可以自己改規則）
                subfolder = table_root / md_file.stem

                # 👉 確保資料夾存在
                subfolder.mkdir(parents=True, exist_ok=True)

                # 👉 寫入 table
                with open(subfolder / table_name, "w", encoding="utf-8") as tf:
                    tf.writelines(block)

                # log
                writer.writerow([
                    md_path.name,
                    table_name,
                    f"{len(block)} 行"
                ])

                # 在原文放標記
                new_lines.append(f"[TABLE_REMOVED id={table_tag}]\n")

            else:
                new_lines.append(lines[i])
                i += 1

        return new_lines

    # ========= 4. 主流程 =========
    LOG_PATH = LOG_DIR / "table_log.csv"

    with open(LOG_PATH, "w", encoding="utf-8-sig", newline="") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(["來源檔案", "表格檔名", "行數"])

        files = list(working_dir.glob("*.md"))
        print(f"抓到 {len(files)} 個 md 檔")

        for md_file in files:
            new_lines = process_file(md_file, writer)

            output_path = working_dir / md_file.name
            with open(output_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

    print("[OK] 表格抽取完成")
def extract_heading_lines():
    import re
    from pathlib import Path

    OUT_DIR = RESULT_DIR / "headings"
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # =====================================
    # 🔧 1. pattern registry（辨識）
    # =====================================
    def build_patterns():
        return [
            ("CHAPTER",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*章"),
            ("SECTION",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*節"),
            ("ARTICLE",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*條(?:之\d+)?"),
            ("PARAGRAPH",r"^第\s*([一二三四五六七八九十百0-9]+)\s*項"),
            ("SUBITEM",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*款"),

            ("ITEM_ZH", r"^([一二三四五六七八九十]+)[、．.]"),
            ("ITEM_ZH_BIG", r"^([壹貳參肆伍陸柒捌玖])[、．.]"),
            ("PAREN_ZH_BIG", r"^[（(]([壹貳參肆伍陸柒捌玖拾]+)[）)]"),

            ("PAREN_ZH", r"^[（(]([一二三四五六七八九十]+)[）)]"),
            ("PAREN_NUM", r"^[（(](\d+)[）)]"),

            ("POINT_NUM", r"^(\d+)[\.．、]"),
            ("ALPHA", r"^([a-zA-Z])[\.．、]"),
            ("ROMAN", r"^([ivxlcdmIVXLCDM]+)[\.．、]"),
        ]

    # =====================================
    # 🔧 2. level system（階層）
    # =====================================
    def build_level_maps():
        fixed_level = {
            "CHAPTER": 0,
            "SECTION": 1,
            "ARTICLE": 2,
            "PARAGRAPH": 3,
            "SUBITEM": 4
        }

        dynamic_level_map = {
            "ITEM_ZH": 5,
            "ITEM_ZH_BIG": 5,
            "PAREN_ZH": 6,
            "PAREN_ZH_BIG": 6,
            "PAREN_NUM": 7,
            "POINT_NUM": 7,
            "ALPHA": 8,
            "ROMAN": 9
        }

        return fixed_level, dynamic_level_map

    def get_level(tag_type, fixed, dynamic):
        if tag_type in fixed:
            return fixed[tag_type]
        if tag_type in dynamic:
            return dynamic[tag_type]
        return None

    # =====================================
    # 🔧 3. heading 判斷（🔥核心）
    # =====================================
    def classify_line(line, patterns, prev_line=None):
        

        # 👉 判斷是否為「區塊開頭」
        is_block_start = (
            prev_line is None or
            prev_line.strip() == "" or
            prev_line.startswith("[page") or
            prev_line.startswith("#")
        )

        if not is_block_start:
            return None

        # 👉 原本的匹配
        for tag_type, pattern in patterns:
            m = re.match(pattern, line)
            if m:
                token = m.group(0)
                number = m.group(1) if m.groups() else None

                return {
                    "type": tag_type,
                    "token": token,
                    "number": number
                }

        return None

    # =====================================
    # 🔧 4. block extraction
    # =====================================
    def extract_blocks(lines, patterns, fixed, dynamic):

        blocks = []
        new_lines = []          # 👉 主md（前後包）
        structure_lines = []    # 👉 純tag
        marked_lines = []       # 👉 如果你還要語意版（可選）

        current_block = []
        current_tag = None

        for line in lines:
            stripped = line.strip()
            info = classify_line(stripped, patterns, prev_line=None)
            

            if info:
                level = get_level(info["type"], fixed, dynamic)
                tag = info["token"]

                if current_block:
                    blocks.append(current_block)
                    new_lines.append(f"[/{current_tag}]")

                current_block = [line]
                current_tag = tag

                # 👉 開 tag
                new_lines.append(f"[{tag}]")

                # 🔥 關鍵：保留原始那一行
                new_lines.append(line)

                # 👉 structure
                structure_lines.append(f"[{tag}]")

            else:
                if current_block:
                    current_block.append(line)
                    new_lines.append(line)
                else:
                    new_lines.append(line)

        if current_block:
            blocks.append(current_block)
            new_lines.append(f"[/{current_tag}]")

        return blocks, new_lines, structure_lines

    # =====================================
    # 🔧 5. IO
    # =====================================
    def save_blocks(blocks, path):
        out = []
        for block in blocks:
            out.extend(block)
            out.append("")
        path.write_text("\n".join(out), encoding="utf-8")

    def overwrite(md_file, new_lines, structure_lines):

        # 👉 主md（可讀版）
        md_file.write_text("\n".join(new_lines), encoding="utf-8")

        # 👉 結構檔（另存）
        structure_dir = md_file.parent.parent / "structure"
        structure_dir.mkdir(exist_ok=True)

        structure_file = structure_dir / md_file.name
        structure_file.write_text("\n".join(structure_lines), encoding="utf-8")

    # =====================================
    # 🚀 主流程
    # =====================================
    patterns = build_patterns()
    fixed, dynamic = build_level_maps()

    for md_file in working_dir.glob("*.md"):

        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()


        blocks, new_lines, structure_lines = extract_blocks(lines, patterns, fixed, dynamic)

        save_blocks(blocks, OUT_DIR / md_file.name)
        overwrite(md_file, new_lines, structure_lines)

    print("[OK] 完整 heading parser 重寫完成")
def clean_md_garbage_folder(input_dir, output_dir, header_threshold=3):

    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log_csv_path = RESULT_DIR/"log.csv"
    log_csv_path.parent.mkdir(parents=True, exist_ok=True)

    # ===== pattern =====
    page_patterns = [
        r"^\s*第\s*\d+\s*頁\s*$",
        r"^\s*第\s*\d+\s*頁\s*共\s*\d+\s*頁\s*$",
        r"^\s*[-–—]?\s*\d+\s*[-–—]?\s*$"
    ]

    noise_patterns = [
        r"^\s*\d+\s*$",
        r"\d{2,3}年\d{1,2}月.*臺灣期貨交易所"
    ]

    page_regex = re.compile("|".join(page_patterns), re.IGNORECASE)
    noise_regex = re.compile("|".join(noise_patterns), re.IGNORECASE)

    # ===== CSV log =====
    log_rows = []

    for file in input_dir.glob("*.md"):
        text = file.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()

        file_log = defaultdict(list)

        # ---- 1️⃣ 清頁碼 + OCR ----
        temp_lines = []
        for line in lines:
            s = line.strip()

            if not s:
                continue

            if page_regex.match(s):
                if len(file_log["page"]) < 3:
                    file_log["page"].append(s)
                continue

            if noise_regex.match(s):
                if len(file_log["noise"]) < 3:
                    file_log["noise"].append(s)
                continue

            temp_lines.append(line)

        # ---- 2️⃣ header 偵測（排除 [ 開頭）----
        stripped = [
            l.strip() for l in temp_lines
            if l.strip() and not l.strip().startswith("[")
        ]

        counter = Counter(stripped)

        header_candidates = {
            line for line, count in counter.items()
            if count >= header_threshold and len(line) <= 30
        }

        # ---- 3️⃣ 刪 header（保護 [）----
        final_lines = []
        for line in temp_lines:
            s = line.strip()

            if s.startswith("["):
                final_lines.append(line)
                continue

            if s in header_candidates:
                if len(file_log["header"]) < 3:
                    file_log["header"].append(s)
                continue

            final_lines.append(line)

        # ---- 4️⃣ 寫 md ----
        out_path = output_dir / file.name
        out_path.write_text("\n".join(final_lines), encoding="utf-8")

        # ---- 5️⃣ 寫 log rows ----
        for log_type, items in file_log.items():
            for item in items:
                log_rows.append([file.name, log_type, item])

        print(f"[OK] cleaned: {file.name}")

    # ---- 6️⃣ 輸出 CSV ----
    with open(log_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "type", "content"])
        writer.writerows(log_rows)

    print("[OK] 完成（CSV log 已輸出）")
def build_tree_pipeline():

    input_dir = RESULT_DIR / "structure"
    output_dir = RESULT_DIR / "tree"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ===== 1) 把各種寫法轉成 []（只做標記，不決定層級）=====
    PATTERNS = [
    r"^第\s*[一二三四五六七八九十百0-9]+\s*章",
    r"^第\s*[一二三四五六七八九十百0-9]+\s*節",
    r"^第\s*[一二三四五六七八九十百0-9]+\s*條(?:之[一二三四五六七八九十0-9]+)?",
    r"^第\s*[一二三四五六七八九十百0-9]+\s*項",
    r"^第\s*[一二三四五六七八九十百0-9]+\s*款",
    r"^[一二三四五六七八九十]+[、．.]",
    r"^[壹貳參肆伍陸柒捌玖拾]+[、．.]",
    r"^[（(][一二三四五六七八九十]+[）)]",
    r"^[（(][壹貳參肆伍陸柒捌玖拾]+[）)]",
    r"^[（(]\d+[）)]",
    r"^[０-９\d]+[\.．、]",
    r"^[a-zA-Z][\.．、]",
    r"^[ivxlcdmIVXLCDM]+[\.．、]",
]


    FIXED_LEVEL = {
        "CHAPTER": 0,
        "SECTION": 1,
        "ARTICLE": 2,
        "PARA": 3,
        "SUBITEM": 4,
    }


    @dataclass
    class Node:
        text: str
        level: int
        children: List["Node"] = field(default_factory=list)


    def classify(inner: str) -> Tuple[str, bool]:
        if "章" in inner:
            return "CHAPTER", True
        if "節" in inner:
            return "SECTION", True
        if "條" in inner:
            return "ARTICLE", True
        if "項" in inner:
            return "PARA", True
        if "款" in inner:
            return "SUBITEM", True

        if re.match(r"^[一二三四五六七八九十]+[、．.]$", inner):
            return "ZH_DOT", False
        if re.match(r"^[壹貳參肆伍陸柒捌玖拾]+[、．.]$", inner):
            return "ZH_BIG_DOT", False
        if re.match(r"^[（(][一二三四五六七八九十]+[）)]$", inner):
            return "ZH_PAREN", False
        if re.match(r"^[（(][壹貳參肆伍陸柒捌玖拾]+[）)]$", inner):
            return "ZH_BIG_PAREN", False
        if re.match(r"^[０-９\d]+[\.．、]$", inner):
            return "NUM_DOT", False
        if re.match(r"^[（(]\d+[）)]$", inner):
            return "NUM_PAREN", False
        if re.match(r"^[a-zA-Z][\.．、]$", inner):
            return "ALPHA", False
        if re.match(r"^[ivxlcdmIVXLCDM]+[\.．、]$", inner):
            return "ROMAN", False

        return "OTHER", False


    def normalize_bracket_lines(raw_lines: List[str]) -> List[str]:
        compiled = [re.compile(p) for p in PATTERNS]
        bracket_lines: List[str] = []

        for line in raw_lines:
            s = line.strip()
            if not s:
                continue

            matched = False
            for pattern in compiled:
                match = pattern.match(s)
                if match:
                    bracket_lines.append(f"[{match.group(0)}]")
                    matched = True
                    break

            if not matched:
                bracket_lines.append(s)

        return bracket_lines


    def compute_level(inner: str, stack: List[Node], type_last_level: Dict[str, int]) -> int:
        tag_type, is_fixed = classify(inner)

        if is_fixed:
            return FIXED_LEVEL[tag_type]

        if tag_type in type_last_level:
            return type_last_level[tag_type]

        level = stack[-1].level + 1
        type_last_level[tag_type] = level
        return level


    def dump_tree(node: Node, indent: int = 0, out: List[str] | None = None) -> List[str]:
        if out is None:
            out = []

        if node.text != "ROOT":
            out.append("  " * indent + node.text)

        for child in node.children:
            dump_tree(child, indent + 1, out)

        return out


    def build_tree_for_file(path: Path) -> Tuple[List[str], Dict[str, int]]:
        raw_lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        bracket_lines = normalize_bracket_lines(raw_lines)

        root = Node("ROOT", -1)
        stack: List[Node] = [root]
        type_last_level: Dict[str, int] = {}

        stats = {
            "emitted_nodes": 0,
        }

        for line in bracket_lines:
            s = line.strip()
            if not s:
                continue

            if s.startswith("[") and s.endswith("]"):
                inner = s[1:-1].strip()

                level = compute_level(inner, stack, type_last_level)
                node = Node(s, level)

                while stack and stack[-1].level >= level:
                    stack.pop()

                stack[-1].children.append(node)
                stack.append(node)
                stats["emitted_nodes"] += 1
            else:
                stack[-1].text += "\n" + s

        return dump_tree(root), stats


    summary_lines = [
            "# tree build summary",
            "",
            f"input_dir={input_dir}",
            f"output_dir={output_dir}",
            "",
    ]

    for file_path in sorted(input_dir.glob("*.md")):
        tree_lines, stats = build_tree_for_file(file_path)
        out_path = output_dir / file_path.name
        out_path.write_text("\n".join(tree_lines), encoding="utf-8")

        summary_lines.append(f"## {file_path.name}")
        summary_lines.append(f"- emitted_nodes={stats['emitted_nodes']}")
        summary_lines.append("")

    (output_dir / "_build_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(f"[OK] tree 建置完成：{output_dir}")

        
    
# ========= 執行 =========
if __name__ == "__main__":
    rewrite_page_markers(working_dir)
    extract_tables()
    extract_heading_lines()
    clean_md_garbage_folder(working_dir, working_dir, header_threshold=3)
    build_tree_pipeline()
