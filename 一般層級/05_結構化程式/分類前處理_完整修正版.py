import csv
import re
import shutil
from pathlib import Path
from collections import Counter

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
    # 增加對頁碼與常見雜訊的過濾[cite: 3]
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

    # 1. 權重定義：章 > 節 > 條 > 項 > 款 > 壹 > 一 > (一) > 1 > (1) > 甲 > i > a[cite: 3]
    TAG_WEIGHT = {
        "CHAPTER": 0,       
        "SECTION": 1,       
        "ARTICLE": 2,       
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

    # 2. 定義匹配模式 (強化 Regex 以處理如 $(一)$ 或底線標記)[cite: 3]
    patterns = [
        ("CHAPTER",      re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*章")),
        ("SECTION",      re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*節")),
        ("ARTICLE",      re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*條")),
        ("PARAGRAPH",    re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*項")),
        ("SUBITEM",      re.compile(r"^第\s*([一二三四五六七八九十百0-9]+)\s*款")),
        ("ITEM_ZH_BIG",  re.compile(r"^[$\s_]*([壹貳參肆伍陸柒捌玖拾]+)[、．.][$\s_]*")),
        ("PAREN_ZH_BIG", re.compile(r"^[$\s_]*[（(]([壹貳參肆伍陸柒捌玖拾]+)[）)][$\s_]*")),
        ("ITEM_ZH",      re.compile(r"^[$\s_]*([一二三四五六七八九十]+)[、．.][$\s_]*")),
        ("PAREN_ZH",     re.compile(r"^[$\s_]*[（(]([一二三四五六七八九十]+)[）)][$\s_]*")),
        ("POINT_NUM",    re.compile(r"^[$\s_]*(\d+)[\.．、][$\s_]*")),
        ("PAREN_NUM",    re.compile(r"^[$\s_]*[（(](\d+)[）)][$\s_]*")),
        ("ITEM_TIAN_GAN",re.compile(r"^[$\s_]*([甲乙丙丁戊己庚辛壬癸]+)[、．.][$\s_]*")),
        ("ROMAN_SMALL",  re.compile(r"^[$\s_]*([ivx]+)[\.．、][$\s_]*")),
        ("ALPHA_LOWER",  re.compile(r"^[$\s_]*([a-z])[.．][$\s_]*")),
        ("PAREN_ALPHA",  re.compile(r"^[$\s_]*[（(]([a-z])[）)][$\s_]*")),
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
                    # 清理輔助符號如 $ 或 _ 以獲得乾淨標籤[cite: 3]
                    tag_only = re.sub(r'[\$_\s]', '', m.group(0))
                    current_weight = TAG_WEIGHT[name]
                    
                    # 層級回溯邏輯
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
                # 內容行隨當前層級縮進
                current_indent = "  " * len(stack)
                new_lines.append(f"{current_indent}{line}")

        md_file.write_text("\n".join(new_lines), encoding="utf-8")
        (STRUCTURE_DIR / md_file.name).write_text("\n".join(struct_lines), encoding="utf-8")
        
    print("[OK] Heading 解析：完整層級 Tree 已適配最新格式[cite: 3]")

def build_tree_pipeline():
    """最後的 Tree 輸出階段"""
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