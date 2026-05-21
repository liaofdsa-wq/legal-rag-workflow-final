import pdfplumber
from pathlib import Path

def pdf_to_markdown():
    base_path = Path(__file__).resolve().parent.parent
    package_root = Path(__file__).resolve().parents[1]
    input_dir = package_root / "01_原始PDF" / "法規資料"
    output_dir = package_root / "03_Markdown生成區" / "法規資料_md"

    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_files = list(input_dir.glob("*.pdf"))
    
    if not pdf_files:
        print(f"找不到 PDF 檔案，請檢查路徑：{input_dir}")
        return

    for pdf_path in pdf_files:
        md_filename = pdf_path.stem + ".md"
        output_path = output_dir / md_filename
        print(f"正在處理: {pdf_path.name} -> {md_filename}")

        try:
            with pdfplumber.open(pdf_path) as pdf:
                full_content = []
                for i, page in enumerate(pdf.pages):
                    full_content.append(f"## Page {i+1}\n")
                    
                    # --- 核心邏輯：排除表格文字 ---
                    
                    # 1. 尋找表格範圍 (Bounding Boxes)
                    tables = page.find_tables()
                    table_bboxes = [t.bbox for t in tables]

                    # 定義一個過濾函式：如果文字物件在任何一個表格範圍內，就回傳 False (排除)
                    def not_within_table(obj):
                        # obj 代表頁面上的每一個字元或物件
                        if obj.get("object_type") == "char":
                            x0, top, x1, bottom = obj["x0"], obj["top"], obj["x1"], obj["bottom"]
                            for bbox in table_bboxes:
                                # bbox 格式為 (x0, top, x1, bottom)
                                if (x0 >= bbox[0] and x1 <= bbox[2] and 
                                    top >= bbox[1] and bottom <= bbox[3]):
                                    return False
                        return True

                    # 2. 提取「非表格」區域的文字
                    clean_text = page.filter(not_within_table).extract_text()
                    if clean_text:
                        full_content.append(clean_text + "\n")
                    
                    # 3. 提取表格內容並轉成 Markdown
                    # 直接從剛才 find_tables 得到的物件中取資料，效率更高
                    for table_obj in tables:
                        table_data = table_obj.extract()
                        if not table_data:
                            continue
                            
                        md_table = "\n"
                        for row_idx, row in enumerate(table_data):
                            cleaned_row = [str(cell).replace('\n', ' ') if cell else "" for cell in row]
                            md_table += "| " + " | ".join(cleaned_row) + " |\n"
                            
                            if row_idx == 0:
                                md_table += "|" + "|".join(["---"] * len(row)) + "|\n"
                        
                        full_content.append(md_table + "\n")
                
                # 寫入檔案
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# {pdf_path.stem}\n\n")
                    f.write("\n".join(full_content))
                    
        except Exception as e:
            print(f"處理 {pdf_path.name} 時出錯: {e}")

    print("\n✅ 全部轉換完成！")

if __name__ == "__main__":
    pdf_to_markdown()
