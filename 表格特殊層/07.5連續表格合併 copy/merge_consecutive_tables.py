import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = BASE_DIR / "06_CleanTree生成區" / "法規資料_md_clean" / "法規資料_md"
OUTPUT_DIR = BASE_DIR / "07.6連續表格合併"
LOG_FILENAME = "merge_consecutive_tables_log.csv"


@dataclass
class TableProfile:
    table_id: str
    cr: int
    ml: int | None
    start_idx: int
    end_idx: int
    start_line: str
    end_line: str
    raw_row_lines: list[str]
    parsed_rows: list[list[str]]


@dataclass
class MergeLogEntry:
    file_name: str
    base_table_id: str
    merged_table_id: str
    ml: int
    cr_used: int
    action: str
    status: str


def merge_consecutive_tables(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR):
    # region 小工具
    def is_table_start(line: str):
        return re.match(
            r"^\[TABLE\s+id=(?P<table_id>.+?)(?:\s+cr=(?P<cr>\d+))?(?:\s+ml=(?P<ml>\d+))?\]\s*$",
            line.strip(),
        )

    def is_table_end(line: str):
        return re.match(r"^\[/TABLE id=([^\]]+)\]\s*$", line.strip())

    def parse_markdown_row(line: str):
        stripped = line.strip()
        if "|" not in stripped:
            return None
        return [cell.strip() for cell in stripped.strip("|").split("|")]

    def is_separator_row(cells):
        if not cells:
            return False
        return all(re.fullmatch(r"[-: ]+", cell or "") for cell in cells)

    def get_merge_tag(cell_text: str):
        match = re.match(r"^\[@(\d+)\]", (cell_text or "").strip())
        if not match:
            return None
        return match.group(1)

    def strip_merge_tag(cell_text: str):
        return re.sub(r"^\[@\d+\]\s*", "", (cell_text or "").strip())

    def attach_merge_tag(cell_text: str, tag: str):
        stripped = (cell_text or "").strip()
        if not stripped:
            return f"[@{tag}]"
        if get_merge_tag(stripped) == tag:
            return stripped
        return f"[@{tag}] {stripped}"

    def normalize_cell(cell: str):
        return re.sub(r"\s+", " ", cell or "").strip()

    def join_cells(base: str, extra: str):
        base_text = (base or "").strip()
        extra_text = (extra or "").strip()
        if not extra_text:
            return base_text
        if not base_text:
            return extra_text
        if normalize_cell(base_text) == normalize_cell(extra_text):
            return base_text
        return f"{base_text} {extra_text}"

    def row_to_markdown(cells: list[str], width: int):
        padded = list(cells) + [""] * max(0, width - len(cells))
        return "| " + " | ".join(padded[:width]) + " |"

    def build_separator_row(width: int):
        return "| " + " | ".join(["---"] * max(1, width)) + " |"

    def ensure_width(row: list[str], width: int):
        if len(row) < width:
            row.extend([""] * (width - len(row)))
        return row

    def cut_header_rows(rows: list[list[str]], cr: int):
        return rows[cr:]

    def parse_table_block(lines, start_idx):
        start_match = is_table_start(lines[start_idx])
        if not start_match:
            return None

        table_id = start_match.group("table_id")
        cursor = start_idx + 1
        raw_row_lines = []
        parsed_rows = []

        while cursor < len(lines):
            line = lines[cursor]
            if is_table_end(line):
                return TableProfile(
                    table_id=table_id,
                    cr=int(start_match.group("cr") or "1"),
                    ml=int(start_match.group("ml")) if start_match.group("ml") else None,
                    start_idx=start_idx,
                    end_idx=cursor,
                    start_line=lines[start_idx].rstrip("\n"),
                    end_line=line.rstrip("\n"),
                    raw_row_lines=raw_row_lines,
                    parsed_rows=parsed_rows,
                )

            raw_row_lines.append(line.rstrip("\n"))
            cells = parse_markdown_row(line)
            if cells and not is_separator_row(cells):
                parsed_rows.append(cells)
            cursor += 1

        return None

    def parse_blocks(lines):
        blocks = []
        idx = 0
        while idx < len(lines):
            table = parse_table_block(lines, idx)
            if table:
                blocks.append({"type": "table", "table": table})
                idx = table.end_idx + 1
                continue

            text_lines = []
            start_idx = idx
            while idx < len(lines) and not is_table_start(lines[idx]):
                text_lines.append(lines[idx].rstrip("\n"))
                idx += 1
            blocks.append(
                {
                    "type": "text",
                    "start_idx": start_idx,
                    "end_idx": idx - 1,
                    "lines": text_lines,
                }
            )
        return blocks

    def merge_row_into_last(base_rows: list[list[str]], incoming_row: list[str]):
        if not base_rows:
            base_rows.append(list(incoming_row))
            return

        target = base_rows[-1]
        width = max(len(target), len(incoming_row))
        ensure_width(target, width)
        incoming = list(incoming_row) + [""] * max(0, width - len(incoming_row))
        for col_idx, value in enumerate(incoming):
            target[col_idx] = join_cells(target[col_idx], value)

    def merge_first_row_then_append_rest(base_rows: list[list[str]], rows_to_use: list[list[str]]):
        if not rows_to_use:
            return "no_rows"
        merge_row_into_last(base_rows, rows_to_use[0])
        if len(rows_to_use) > 1:
            base_rows.extend([list(row) for row in rows_to_use[1:]])
            return "merge_first_row_then_append_rest"
        return "merge_first_row_only"

    def build_next_merge_tag(base_rows: list[list[str]], rows_to_use: list[list[str]]):
        next_tag = 1
        for row in base_rows + rows_to_use:
            for cell in row:
                tag = get_merge_tag(cell)
                if tag is not None:
                    next_tag = max(next_tag, int(tag) + 1)
        return next_tag

    def ensure_tagged_cell(row: list[str], col_idx: int, next_tag_ref: list[int]):
        current_value = row[col_idx]
        tag = get_merge_tag(current_value)
        if tag is None:
            tag = str(next_tag_ref[0])
            next_tag_ref[0] += 1
            row[col_idx] = attach_merge_tag(current_value, tag)
        return row[col_idx]

    def build_ml3_carry_sources(base_rows: list[list[str]], carry_cols: set[int]):
        carry_sources: dict[int, tuple[list[str], int]] = {}
        if not base_rows:
            return carry_sources

        target = base_rows[-1]
        for col_idx in carry_cols:
            if col_idx >= len(target):
                continue
            if normalize_cell(strip_merge_tag(target[col_idx])) == "":
                continue
            carry_sources[col_idx] = (target, col_idx)
        return carry_sources

    def render_table(table: TableProfile):
        parsed_rows = [list(row) for row in table.parsed_rows]
        width = max((len(row) for row in parsed_rows), default=1)
        lines = [table.start_line]
        if parsed_rows:
            lines.append(row_to_markdown(parsed_rows[0], width))
            lines.append(build_separator_row(width))
            for row in parsed_rows[1:]:
                lines.append(row_to_markdown(row, width))
        lines.append(table.end_line)
        return [line + "\n" for line in lines]
    # endregion

    # region 規則
    def handle_ml1(base_rows, lower_table):
        rows_to_use = cut_header_rows(lower_table.parsed_rows, lower_table.cr)
        return {
            "action": merge_first_row_then_append_rest(base_rows, rows_to_use),
            "cr_used": lower_table.cr,
        }

    def handle_ml2(base_rows, lower_table):
        return {
            "action": merge_first_row_then_append_rest(base_rows, lower_table.parsed_rows),
            "cr_used": 0,
        }

    def handle_ml3(base_rows, lower_table):
        rows_to_use = cut_header_rows(lower_table.parsed_rows, lower_table.cr)
        if not rows_to_use:
            return {"action": "no_rows", "cr_used": lower_table.cr}

        normalized_rows = [list(row) for row in rows_to_use]
        if not base_rows:
            base_rows.extend(normalized_rows)
            action = "append_all_rows_no_base"
            if len(normalized_rows) == 1:
                action = "append_first_row_no_base"
            return {"action": action, "cr_used": lower_table.cr}

        next_tag_ref = [build_next_merge_tag(base_rows, normalized_rows)]
        carry_cols = {0, 1, 2}
        required_carry_cols = {1, 2}
        carry_sources = build_ml3_carry_sources(base_rows, carry_cols)

        appended_any_row = False
        carried_any_cell = False
        extended_any_row = False

        for row_idx, source_row in enumerate(normalized_rows):
            working_row = list(source_row)
            width = len(working_row)
            if base_rows:
                width = max(width, len(base_rows[-1]))
            if width:
                ensure_width(working_row, width)

            for col_idx in carry_cols:
                if col_idx >= len(working_row):
                    continue
                current_value = working_row[col_idx]
                if normalize_cell(strip_merge_tag(current_value)) != "":
                    carry_sources[col_idx] = (working_row, col_idx)
                    continue

                source_ref = carry_sources.get(col_idx)
                if source_ref is None:
                    continue

                source_row_ref, source_col_idx = source_ref
                if normalize_cell(strip_merge_tag(source_row_ref[source_col_idx])) == "":
                    continue

                tagged_value = ensure_tagged_cell(source_row_ref, source_col_idx, next_tag_ref)
                working_row[col_idx] = tagged_value
                carry_sources[col_idx] = (working_row, col_idx)
                carried_any_cell = True

            for col_idx in required_carry_cols:
                if col_idx >= len(working_row):
                    continue
                if normalize_cell(strip_merge_tag(working_row[col_idx])) != "":
                    continue
                source_ref = carry_sources.get(col_idx)
                if source_ref is None:
                    continue
                source_row_ref, source_col_idx = source_ref
                if normalize_cell(strip_merge_tag(source_row_ref[source_col_idx])) == "":
                    continue
                tagged_value = ensure_tagged_cell(source_row_ref, source_col_idx, next_tag_ref)
                working_row[col_idx] = tagged_value
                carry_sources[col_idx] = (working_row, col_idx)
                carried_any_cell = True

            base_rows.append(working_row)
            appended_any_row = True

            if row_idx > 0:
                extended_any_row = True

            for col_idx in carry_cols:
                if col_idx >= len(working_row):
                    continue
                if normalize_cell(strip_merge_tag(working_row[col_idx])) == "":
                    continue
                carry_sources[col_idx] = (working_row, col_idx)

        action = "append_rows"
        if carried_any_cell and extended_any_row:
            action = "carry_forward_then_append_rows"
        elif carried_any_cell:
            action = "carry_forward_rows"
        elif extended_any_row:
            action = "append_rows_after_first"

        if not appended_any_row:
            action = "no_rows"

        return {"action": action, "cr_used": lower_table.cr}

    def handle_ml4(base_rows, lower_table):
        rows_to_use = cut_header_rows(lower_table.parsed_rows, lower_table.cr)
        return {
            "action": merge_first_row_then_append_rest(base_rows, rows_to_use),
            "cr_used": lower_table.cr,
        }

    def handle_ml5(base_rows, lower_table):
        return {
            "action": merge_first_row_then_append_rest(base_rows, lower_table.parsed_rows),
            "cr_used": 0,
        }

    def build_ml_decision(base_rows, lower_table):
        if lower_table.ml == 1:
            return handle_ml1(base_rows, lower_table)
        if lower_table.ml == 2:
            return handle_ml2(base_rows, lower_table)
        if lower_table.ml == 3:
            return handle_ml3(base_rows, lower_table)
        if lower_table.ml == 4:
            return handle_ml4(base_rows, lower_table)
        if lower_table.ml == 5:
            return handle_ml5(base_rows, lower_table)
        return None
    # endregion

    # region 主流程
    def merge_file(md_file: Path, input_root: Path, output_root: Path):
        lines = md_file.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
        blocks = parse_blocks(lines)

        output_blocks = []
        pending_text_lines: list[str] = []
        logs: list[MergeLogEntry] = []

        for block in blocks:
            if block["type"] == "text":
                pending_text_lines.extend(block["lines"])
                continue

            table: TableProfile = block["table"]
            can_merge = (
                table.ml is not None
                and output_blocks
                and output_blocks[-1]["type"] == "table"
            )

            if can_merge:
                base_table: TableProfile = output_blocks[-1]["table"]
                decision = build_ml_decision(base_table.parsed_rows, table)
                if decision is not None:
                    action = decision["action"]
                    if pending_text_lines:
                        action += "_drop_intervening_text"
                    logs.append(
                        MergeLogEntry(
                            file_name=md_file.name,
                            base_table_id=base_table.table_id,
                            merged_table_id=table.table_id,
                            ml=table.ml,
                            cr_used=decision["cr_used"],
                            action=action,
                            status="merged",
                        )
                    )
                    pending_text_lines = []
                    continue

            if pending_text_lines:
                output_blocks.append({"type": "text", "lines": list(pending_text_lines)})
                pending_text_lines = []
            output_blocks.append({"type": "table", "table": table})

        if pending_text_lines:
            output_blocks.append({"type": "text", "lines": list(pending_text_lines)})

        output_lines: list[str] = []
        for block in output_blocks:
            if block["type"] == "text":
                output_lines.extend([line + "\n" for line in block["lines"]])
            else:
                output_lines.extend(render_table(block["table"]))

        relative_path = md_file.relative_to(input_root)
        output_path = output_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("".join(output_lines), encoding="utf-8")
        return logs

    def write_merge_log(log_entries: list[MergeLogEntry], output_root: Path):
        log_path = output_root / LOG_FILENAME
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "file_name",
                    "base_table_id",
                    "merged_table_id",
                    "ml",
                    "cr_used",
                    "action",
                    "status",
                ]
            )
            for entry in log_entries:
                writer.writerow(
                    [
                        entry.file_name,
                        entry.base_table_id,
                        entry.merged_table_id,
                        entry.ml,
                        entry.cr_used,
                        entry.action,
                        entry.status,
                    ]
                )

    output_dir.mkdir(parents=True, exist_ok=True)
    md_files = sorted(input_dir.rglob("*.md"))
    all_logs: list[MergeLogEntry] = []

    for md_file in md_files:
        all_logs.extend(merge_file(md_file, input_dir, output_dir))

    write_merge_log(all_logs, output_dir)
    print(f"[OK] merged {len(md_files)} files into {output_dir}")
    print(f"[OK] log written to {output_dir / LOG_FILENAME}")
    # endregion


def main():
    parser = argparse.ArgumentParser(description="Merge consecutive markdown tables based on ml tags.")
    parser.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    merge_consecutive_tables(args.input_dir, args.output_dir)


if __name__ == "__main__":
    main()
