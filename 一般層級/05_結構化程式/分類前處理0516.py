import csv
import re
import shutil
from pathlib import Path
from collections import Counter

# ── Codex 版移植所需的額外 import ──────────────────────────────
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

# 1. 路徑定義
# 這裡預設目錄結構，請根據您的環境調整
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = PACKAGE_ROOT / "04_Markdown精修區" / "法規資料_md"
RESULT_DIR = PACKAGE_ROOT / "06_CleanTree生成區" / "法規資料_md_clean"
LOG_DIR = RESULT_DIR / "log"

# 初始化目錄
if RESULT_DIR.exists():
    shutil.rmtree(RESULT_DIR)

working_dir = RESULT_DIR / SOURCE_DIR.name
shutil.copytree(SOURCE_DIR, working_dir)
LOG_DIR.mkdir(parents=True, exist_ok=True)

def rewrite_page_markers(working_dir):
    """將 ## Page X 轉換為 [page X] 格式"""
    page_pattern = re.compile(r"^\s*##\s*Page\s*(\d+)", re.IGNORECASE)
    for md_file in Path(working_dir).glob("*.md"):
        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines = [f"[page {m.group(1)}]" if (m := page_pattern.match(line.strip())) else line for line in lines]
        md_file.write_text("\n".join(new_lines), encoding="utf-8")
    print("[OK] 頁碼已轉換為 [page X]")

def extract_tables():
    """抽取 Markdown 中的表格並另存新檔"""
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
    """清理重複頁首、頁尾與特定雜訊"""
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

def extract_heading_lines():
    """解析標題層級，強化對法規文本（含甲乙丙、i ii iii、帶符號標記）的識別"""
    OUT_DIR = RESULT_DIR / "headings"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    STRUCTURE_DIR = RESULT_DIR / "structure"
    STRUCTURE_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 權重定義：章 > 節 > 條/點 > 項 > 款 > 壹 > 一 > (一) > 1 > (1)
    TAG_WEIGHT = {
        "CHAPTER": 0,       
        "SECTION": 1,       
        "ARTICLE": 2,       
        "POINT_ZH_MAIN": 2, # 新增：第 X 點，權重與條相同
        "PARAGRAPH": 3,     
        "SUBITEM": 4,       
        "ITEM_ZH_BIG": 5,   
        "PAREN_ZH_BIG": 6,  
        "ITEM_ZH": 7,       
        "PAREN_ZH": 8,      
        "POINT_NUM": 9,     
        "PAREN_NUM": 10,    
        "ITEM_TIAN_GAN": 11,
        "ROMAN_SMALL": 12,  
        "ALPHA_LOWER": 13,  
        "PAREN_ALPHA": 14   
    }

    # 2. 定義匹配模式
    patterns = [
        ("CHAPTER",       re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*章")),
        ("SECTION",       re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*節")),
        ("ARTICLE",       re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*條")),
        ("POINT_ZH_MAIN", re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*點")), # 新增：匹配「第一點」、「第1點」
        ("PARAGRAPH",     re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*項")),
        ("SUBITEM",       re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*款")),
        ("ITEM_ZH_BIG",   re.compile(r"^[$\s_]*([壹貳參肆伍陸柒捌玖拾]+)[、．.][$\s_]*")),
        ("PAREN_ZH_BIG",  re.compile(r"^[$\s_]*[（(]([壹貳參肆伍陸柒捌玖拾]+)[）)][$\s_]*")),
        ("ITEM_ZH",       re.compile(r"^[$\s_]*([一二三四五六七八九十]+)[、．.][$\s_]*")),
        ("PAREN_ZH",      re.compile(r"^[$\s_]*[（(]([一二三四五六七八九十]+)[）)][$\s_]*")),
        ("POINT_NUM",     re.compile(r"^[$\s_]*(\d+)[\.．、][$\s_]*")),
        ("PAREN_NUM",     re.compile(r"^[$\s_]*[（(](\d+)[）)][$\s_]*")),
        ("ITEM_TIAN_GAN", re.compile(r"^[$\s_]*([甲乙丙丁戊己庚辛壬癸]+)[、．.][$\s_]*")),
        ("ROMAN_SMALL",   re.compile(r"^[$\s_]*([ivx]+)[\.．、][$\s_]*")),
        ("ALPHA_LOWER",   re.compile(r"^[$\s_]*([a-z])[.．][$\s_]*")),
        ("PAREN_ALPHA",   re.compile(r"^[$\s_]*[（(]([a-z])[）)][$\s_]*")),
    ]

    for md_file in working_dir.glob("*.md"):
        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines()
        new_lines, struct_lines = [], []
        stack = []

        for line in lines:
            s = line.strip()
            if not s:
                new_lines.append(line)
                continue

            matched = False
            for name, pat in patterns:
                if m := pat.match(s):
                    tag_only = re.sub(r'[\$_\s]', '', m.group(0))
                    current_weight = TAG_WEIGHT[name]
                    
                    while stack and TAG_WEIGHT[stack[-1]['type']] >= current_weight:
                        stack.pop()
                    
                    level = len(stack)
                    stack.append({"type": name, "weight": current_weight})
                    
                    indent = "  " * level
                    new_lines.append(f"{indent}[{s}]")
                    struct_lines.append(f"{indent}[{tag_only}]")
                    matched = True
                    break
            
            if not matched:
                current_indent = "  " * len(stack)
                new_lines.append(f"{current_indent}{line}")

        md_file.write_text("\n".join(new_lines), encoding="utf-8")
        (STRUCTURE_DIR / md_file.name).write_text("\n".join(struct_lines), encoding="utf-8")
        
    print("[OK] Heading 解析：完整層級 Tree 已適配最新格式")

def build_tree_pipeline():
    """最後的 Tree 輸出階段"""
    input_dir = RESULT_DIR / "structure"
    output_dir = RESULT_DIR / "tree"
    output_dir.mkdir(parents=True, exist_ok=True)
    for file_path in input_dir.glob("*.md"):
        shutil.copy(file_path, output_dir / file_path.name)
    print(f"[OK] Tree 輸出完成")

# ══════════════════════════════════════════════════════════════════════════════
# 以下為從 Codex 版移植的強化函式
# ══════════════════════════════════════════════════════════════════════════════

def clean_md_garbage_folder_with_log(input_dir, output_dir, header_threshold=3):
    """
    【移植自 Codex 版】
    在最終版 clean_md_garbage_folder 的基礎上，新增 CSV log 機制：
    - 記錄每個檔案中被刪除的頁碼、noise、重複 header 各條目
    - 輸出至 RESULT_DIR/clean_log.csv，每類最多記錄 3 筆範例
    最終版原本的清理邏輯（page_regex、noise_regex、header 偵測）完全不變。
    """
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 與最終版完全相同的 regex ──────────────────────────────────
    page_regex  = re.compile(r"^\s*(第\s*\d+\s*頁|第\s*\d+\s*頁\s*共\s*\d+\s*頁|[-–—]?\s*\d+\s*[-–—]?)\s*$", re.I)
    noise_regex = re.compile(r"^\s*\d+\s*$|\d{2,3}年\d{1,2}月.*臺灣期貨交易所")

    # ── Codex 版新增：log 收集容器 ────────────────────────────────
    log_csv_path = LOG_DIR / "clean_log.csv"
    log_rows: list = []

    for file in input_dir.glob("*.md"):
        lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()

        # ── Codex 版新增：per-file log ────────────────────────────
        file_log: Dict[str, list] = defaultdict(list)

        # ---- step 1：清頁碼 + noise（與最終版邏輯相同，加 log）----
        temp_lines = []
        for l in lines:
            s = l.strip()
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
            temp_lines.append(l)

        # ---- step 2：header 偵測（與最終版完全相同）----------------
        stripped = [l.strip() for l in temp_lines if not l.strip().startswith("[")]
        counter  = Counter(stripped)
        headers  = {line for line, count in counter.items() if count >= header_threshold and len(line) <= 30}

        # ---- step 3：刪 header（加 log）----------------------------
        final_lines = []
        for l in temp_lines:
            s = l.strip()
            if s.startswith("["):
                final_lines.append(l)
                continue
            if s in headers:
                if len(file_log["header"]) < 3:
                    file_log["header"].append(s)
                continue
            final_lines.append(l)

        # ---- step 4：寫出（與最終版相同）---------------------------
        (output_dir / file.name).write_text("\n".join(final_lines), encoding="utf-8")

        # ---- step 5：累積 log rows ----------------------------------
        for log_type, items in file_log.items():
            for item in items:
                log_rows.append([file.name, log_type, item])

    # ── 輸出 CSV log ──────────────────────────────────────────────
    with open(log_csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["檔案名稱", "刪除類型", "被刪內容"])
        writer.writerows(log_rows)

    print(f"[OK] 垃圾清理完成（含 log → {log_csv_path}）")


def build_tree_pipeline_with_parse():
    """
    【移植自 Codex 版 - 嚴格維持架構與羅馬數字對齊修正版】
    在最終版 build_tree_pipeline 的基礎上，以真正的樹狀解析取代單純 shutil.copy：
    - 嚴格維持原本架構：只讀取 structure/*.md (純標籤骨架)，絕不包含任何法規內文。
    - 核心修正：將羅馬數字、英文字母、天干等標籤從動態層級改為 FIXED_LEVEL 固定層級定義，
      徹底解決 [i.][ii.][iii.] 被當作上下級、導致縮排歪斜的問題。
    """
    input_dir  = RESULT_DIR / "structure"  # 100% 維持原本輸入源，只處理純標籤
    output_dir = RESULT_DIR / "tree"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 與原本完全相同的 PATTERNS ────────────────────────────────
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

    # ── 2. 核心修正：為所有子標籤分配固定層級，避免動態遞增 ─────────
    FIXED_LEVEL: Dict[str, int] = {
        "CHAPTER":      0,  # 第X章
        "SECTION":      1,  # 第X節
        "ARTICLE":      2,  # 第X條
        "PARA":         3,  # 第X項
        "SUBITEM":      4,  # 第X款
        "ZH_BIG_DOT":   5,  # 壹、
        "ZH_BIG_PAREN": 6,  # (壹)
        "ZH_DOT":       7,  # 一、
        "ZH_PAREN":     8,  # (一)
        "NUM_DOT":      9,  # 1. 
        "NUM_PAREN":    10, # (1)
        "TIAN_GAN":     11, # 甲、乙、丙
        "ROMAN":        12, # i. ii. iii. (修正關鍵：有了固定層級，同級標籤便會完美對齊)
        "ALPHA":        13, # a. b. c.
    }

    @dataclass
    class Node:
        text: str
        level: int
        children: List["Node"] = field(default_factory=list)

    # ── 3. 將動態型態正式改為 is_fixed=True ────────────────────────
    def classify(inner: str) -> Tuple[str, bool]:
        if "章" in inner: return "CHAPTER", True
        if "節" in inner: return "SECTION", True
        if "條" in inner: return "ARTICLE", True
        if "項" in inner: return "PARA",    True
        if "款" in inner: return "SUBITEM", True
        if re.match(r"^[一二三四五六七八九十]+[、．.]$", inner):       return "ZH_DOT",      True
        if re.match(r"^[壹貳參肆伍陸柒捌玖拾]+[、．.]$", inner):      return "ZH_BIG_DOT",  True
        if re.match(r"^[（(][一二三四五六七八九十]+[）)]$", inner):    return "ZH_PAREN",    True
        if re.match(r"^[（(][壹貳參肆伍陸柒捌玖拾]+[）)]$", inner):   return "ZH_BIG_PAREN",True
        if re.match(r"^[０-９\d]+[\.．、]$", inner):                   return "NUM_DOT",     True
        if re.match(r"^[（(]\d+[）)]$", inner):                        return "NUM_PAREN",   True
        if re.match(r"^[甲乙丙丁戊己庚辛壬癸]+[、．.]$", inner):       return "TIAN_GAN",    True
        if re.match(r"^[a-zA-Z][\.．、]$", inner):                     return "ALPHA",       True
        if re.match(r"^[ivxlcdmIVXLCDM]+[\.．、]$", inner):           return "ROMAN",       True
        return "OTHER", False

    # ── 4. 與原本完全相同的正規化邏輯 ───────────────────────
    def normalize_bracket_lines(raw_lines: List[str]) -> List[str]:
        compiled = [re.compile(p) for p in PATTERNS]
        result: List[str] = []
        for line in raw_lines:
            s = line.strip()
            if not s:
                continue
            matched = False
            for pat in compiled:
                m = pat.match(s)
                if m:
                    result.append(f"[{m.group(0)}]")
                    matched = True
                    break
            if not matched:
                result.append(s)
        return result

    # ── 5. 與原本完全相同的層級計算，但現在皆透過 FIXED_LEVEL 查表 ────
    def compute_level(inner: str, stack: List[Node], type_last_level: Dict[str, int]) -> int:
        tag_type, is_fixed = classify(inner)
        if is_fixed:
            return FIXED_LEVEL[tag_type]
        if tag_type in type_last_level:
            return type_last_level[tag_type]
        level = stack[-1].level + 1
        type_last_level[tag_type] = level
        return level

    # ── 6. 與原本完全相同的樹狀輸出邏輯 ───────────────────────────
    def dump_tree(node: Node, indent: int = 0, out: List[str] = None) -> List[str]:
        if out is None:
            out = []
        if node.text != "ROOT":
            out.append("  " * indent + node.text)
        for child in node.children:
            dump_tree(child, indent + 1, out)
        return out

    # ── 7. 與原本完全相同的純骨架建樹流程（完美維持原本架構） ────────
    def build_tree_for_file(path: Path) -> Tuple[List[str], Dict[str, int]]:
        raw_lines     = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        bracket_lines = normalize_bracket_lines(raw_lines)
        root  = Node("ROOT", -1)
        stack: List[Node] = [root]
        type_last_level: Dict[str, int] = {}
        stats = {"emitted_nodes": 0}
        for line in bracket_lines:
            s = line.strip()
            if not s:
                continue
            if s.startswith("[") and s.endswith("]"):
                inner = s[1:-1].strip()
                level = compute_level(inner, stack, type_last_level)
                node  = Node(s, level)
                while stack and stack[-1].level >= level:
                    stack.pop()
                stack[-1].children.append(node)
                stack.append(node)
                stats["emitted_nodes"] += 1
            else:
                stack[-1].text += "\n" + s
        return dump_tree(root), stats

    # ── 8. 與原本完全相同的主流程 ──────────────────────────────────
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
    print(f"[OK] Tree 建置完成（含結構解析 → {output_dir}）")


# ══════════════════════════════════════════════════════════════════════════════
# 主程式：執行順序與最終版相同，以強化版函式取代對應的原版呼叫
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    rewrite_page_markers(working_dir)
    extract_tables()
    clean_md_garbage_folder_with_log(working_dir, working_dir)   # 取代 clean_md_garbage_folder
    extract_heading_lines()
    build_tree_pipeline_with_parse()                             # 取代 build_tree_pipeline
