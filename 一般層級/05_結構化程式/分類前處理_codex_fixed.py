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
    - 從 md 抓出真正的 Markdown 表格區塊
    - 非表格的條文不要誤刪
    - 原文移除並加標記
    - 表格另存
    - 紀錄 log
    """

    # ========= 1. 判斷是否為表格行 =========
    def split_table_cols(line: str):
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|"):
            s = s[:-1]
        return [c.strip() for c in s.split("|")]

    def is_table_separator(line: str) -> bool:
        """判斷是否為 Markdown 表格分隔線，例如 |---|---|。"""
        s = line.strip()
        if s.count("|") < 2:
            return False

        cols = [c for c in split_table_cols(s) if c]
        if len(cols) < 2:
            return False

        return all(re.fullmatch(r":?-{3,}:?", c.replace(" ", "")) for c in cols)

    def is_table_candidate_line(line: str) -> bool:
        """先抓可能是表格的行，但不代表一定是真的表格。"""
        s = line.strip()
        if not s:
            return False

        # 避免把 [壹、]、[page 1]、[TABLE_REMOVED] 這種標記判成表格
        if s.startswith("[") and s.endswith("]"):
            return False

        # Markdown 表格至少應該有兩個 |，代表至少兩欄
        if s.count("|") < 2:
            return False

        cols = [c for c in split_table_cols(s) if c]
        return len(cols) >= 2

    def is_table_line(line: str) -> bool:
        return is_table_candidate_line(line) or is_table_separator(line)

    def is_real_table_block(block: List[str]) -> bool:
        """整塊判斷，避免只有一行含 | 就被誤判為表格。"""
        if len(block) < 2:
            return False

        # 有 Markdown 分隔線時，幾乎可視為正式表格
        if any(is_table_separator(line) for line in block):
            return True

        # 沒有分隔線時，至少連續 3 行都像表格，才抽出
        if len(block) >= 3 and all(is_table_candidate_line(line) for line in block):
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

        if current_block:
            blocks.append(current_block)

        return blocks

    # ========= 3. 單檔處理 =========
    def process_file(md_path: Path, writer):
        with open(md_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        new_lines = []
        table_id = 0
        i = 0

        while i < len(lines):
            if is_table_line(lines[i]):
                block = []
                while i < len(lines) and is_table_line(lines[i]):
                    block.append(lines[i])
                    i += 1

                # 不是完整表格區塊，就原樣放回，不移除
                if not is_real_table_block(block):
                    new_lines.extend(block)
                    continue

                table_id += 1
                table_tag = f"{md_path.stem}_table_{table_id}"
                table_name = f"{table_tag}.md"

                table_root = RESULT_DIR / "tables"
                subfolder = table_root / md_path.stem
                subfolder.mkdir(parents=True, exist_ok=True)

                with open(subfolder / table_name, "w", encoding="utf-8") as tf:
                    tf.writelines(block)

                writer.writerow([
                    md_path.name,
                    table_name,
                    f"{len(block)} 行"
                ])

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
            ("ARTICLE",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*條(?:之[一二三四五六七八九十0-9]+)?"),
            ("PARAGRAPH",r"^第\s*([一二三四五六七八九十百0-9]+)\s*項"),
            ("SUBITEM",  r"^第\s*([一二三四五六七八九十百0-9]+)\s*款"),

            ("ITEM_ZH_BIG", r"^([壹貳參肆伍陸柒捌玖拾]+)[、．.]"),
            ("ITEM_ZH", r"^([一二三四五六七八九十]+)[、．.]"),
            ("PAREN_ZH_BIG", r"^[（(]([壹貳參肆伍陸柒捌玖拾]+)[）)]"),
            ("PAREN_ZH", r"^[（(]([一二三四五六七八九十]+)[）)]"),
            ("POINT_NUM", r"^(\d+)[\.．、]"),
            ("PAREN_NUM", r"^[（(](\d+)[）)]"),
            ("GAN_DOT", r"^([甲乙丙丁戊己庚辛壬癸])[、．.]"),
            ("GAN_PAREN", r"^[（(]([甲乙丙丁戊己庚辛壬癸])[）)]"),
            ("ROMAN", r"^([ivxlcdmIVXLCDM]+)[\.．、]"),
            ("ALPHA", r"^([a-zA-Z])[\.．、]"),
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
            "ITEM_ZH_BIG": 5,
            "ITEM_ZH": 6,
            "PAREN_ZH": 7,
            "PAREN_ZH_BIG": 7,
            "POINT_NUM": 8,
            "PAREN_NUM": 9,
            "GAN_DOT": 10,
            "GAN_PAREN": 11,
            "ALPHA": 12,
            "ROMAN": 13,
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
        # 不再限制一定要在空白行或 page 後面，避免漏抓條列層級。
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
        r"^[壹貳參肆伍陸柒捌玖拾]+[、．.]",
        r"^[一二三四五六七八九十]+[、．.]",
        r"^[（(][壹貳參肆伍陸柒捌玖拾]+[）)]",
        r"^[（(][一二三四五六七八九十]+[）)]",
        r"^[０-９\d]+[\.．、]",
        r"^[（(]\d+[）)]",
        r"^[甲乙丙丁戊己庚辛壬癸][、．.]",
        r"^[（(][甲乙丙丁戊己庚辛壬癸][）)]",
        r"^[ivxlcdmIVXLCDM]+[\.．、]",
        r"^[a-zA-Z][\.．、]",
    ]

    # rank 是相對順序，不是固定縮排層級。
    # 用 rank 找父層後，實際 level 會根據當前文件自動從 0 開始。
    TYPE_RANK = {
        "CHAPTER": 0,
        "SECTION": 1,
        "ARTICLE": 2,
        "PARA": 3,
        "SUBITEM": 4,
        "ZH_BIG_DOT": 5,
        "ZH_DOT": 6,
        "ZH_BIG_PAREN": 7,
        "ZH_PAREN": 7,
        "NUM_DOT": 8,
        "NUM_PAREN": 9,
        "GAN_DOT": 10,
        "GAN_PAREN": 11,
        "ALPHA": 12,
        "ROMAN": 13,
        "OTHER": 99,
    }

    ROMAN_MAP = {
        "i": 1,
        "ii": 2,
        "iii": 3,
        "iv": 4,
        "v": 5,
        "vi": 6,
        "vii": 7,
        "viii": 8,
        "ix": 9,
        "x": 10,
        "xi": 11,
        "xii": 12,
        "xiii": 13,
        "xiv": 14,
        "xv": 15,
        "xvi": 16,
        "xvii": 17,
        "xviii": 18,
        "xix": 19,
        "xx": 20,
    }

    @dataclass
    class Node:
        text: str
        level: int
        rank: int
        children: List["Node"] = field(default_factory=list)

    def roman_value(inner: str | None):
        if not inner:
            return None

        m = re.fullmatch(r"([ivxlcdmIVXLCDM]+)[\.．、]", inner.strip())
        if not m:
            return None

        token = m.group(1).lower()
        return ROMAN_MAP.get(token)

    def should_be_roman(inner: str, prev_inner: str | None = None, next_inner: str | None = None) -> bool:
        cur = roman_value(inner)
        if cur is None:
            return False

        token = re.sub(r"[\.．、]$", "", inner.strip()).lower()

        # ii. iii. iv. 這種兩個字以上，直接當羅馬數字
        if len(token) >= 2:
            return True

        prev_val = roman_value(prev_inner)
        next_val = roman_value(next_inner)

        # i. 後面接 ii.，代表 i. 是羅馬數字
        if next_val == cur + 1:
            return True

        # v. 前面是 iv.，或後面是 vi.，代表 v. 是羅馬數字
        if prev_val == cur - 1 or next_val == cur + 1:
            return True

        return False

    def classify(inner: str, prev_inner: str | None = None, next_inner: str | None = None) -> str:
        if "章" in inner:
            return "CHAPTER"
        if "節" in inner:
            return "SECTION"
        if "條" in inner:
            return "ARTICLE"
        if "項" in inner:
            return "PARA"
        if "款" in inner:
            return "SUBITEM"

        if re.match(r"^[壹貳參肆伍陸柒捌玖拾]+[、．.]$", inner):
            return "ZH_BIG_DOT"
        if re.match(r"^[一二三四五六七八九十]+[、．.]$", inner):
            return "ZH_DOT"
        if re.match(r"^[（(][壹貳參肆伍陸柒捌玖拾]+[）)]$", inner):
            return "ZH_BIG_PAREN"
        if re.match(r"^[（(][一二三四五六七八九十]+[）)]$", inner):
            return "ZH_PAREN"
        if re.match(r"^[０-９\d]+[\.．、]$", inner):
            return "NUM_DOT"
        if re.match(r"^[（(]\d+[）)]$", inner):
            return "NUM_PAREN"
        if re.match(r"^[甲乙丙丁戊己庚辛壬癸][、．.]$", inner):
            return "GAN_DOT"
        if re.match(r"^[（(][甲乙丙丁戊己庚辛壬癸][）)]$", inner):
            return "GAN_PAREN"

        # 先用前後文判斷 i. v. x. 到底是不是羅馬數字
        if should_be_roman(inner, prev_inner, next_inner):
            return "ROMAN"

        # 如果不是羅馬序列，再當英文字母
        if re.match(r"^[a-zA-Z][\.．、]$", inner):
            return "ALPHA"

        return "OTHER"

    def normalize_bracket_lines(raw_lines: List[str]) -> List[str]:
        compiled = [re.compile(p) for p in PATTERNS]
        bracket_lines: List[str] = []

        for line in raw_lines:
            s = line.strip()
            if not s:
                continue

            # structure 檔本來就是 [壹、] 這種格式，保留即可
            if s.startswith("[") and s.endswith("]"):
                bracket_lines.append(s)
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

    def find_near_inner(lines: List[str], idx: int, step: int):
        j = idx + step
        while 0 <= j < len(lines):
            t = lines[j].strip()
            if t.startswith("[") and t.endswith("]") and not t.startswith("[/"):
                return t[1:-1].strip()
            j += step
        return None

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

        root = Node("ROOT", -1, -1)
        stack: List[Node] = [root]

        stats = {
            "emitted_nodes": 0,
        }

        for idx, line in enumerate(bracket_lines):
            s = line.strip()
            if not s:
                continue

            if s.startswith("[") and s.endswith("]") and not s.startswith("[/"):
                inner = s[1:-1].strip()

                prev_inner = find_near_inner(bracket_lines, idx, -1)
                next_inner = find_near_inner(bracket_lines, idx, 1)
                tag_type = classify(inner, prev_inner, next_inner)
                rank = TYPE_RANK.get(tag_type, TYPE_RANK["OTHER"])

                # 找上一個 rank 比自己小的節點當父節點。
                # 同 rank 代表同層，所以要先 pop。
                while stack and stack[-1].rank >= rank:
                    stack.pop()

                parent = stack[-1] if stack else root
                level = parent.level + 1

                node = Node(s, level, rank)
                parent.children.append(node)
                stack.append(node)
                stats["emitted_nodes"] += 1
            else:
                # 若 structure 中有非 tag 文字，併到目前節點文字後面
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
    # 先清頁首、頁碼、重複文字，再抽 heading，避免每頁頁首都變成 [壹、]
    clean_md_garbage_folder(working_dir, working_dir, header_threshold=3)
    extract_heading_lines()
    build_tree_pipeline()
