# Agent Notes For Scripts

## Main Order

1. `01_build_structured_json.py`
   - Input: `../../../../07_CleanTree精修區/法規資料_md_clean`
   - Output: `../data/json` and `../data/summary`
   - Run after `07_CleanTree精修區` has the accepted clean md / tree / tables.

2. `02_embed_structured_modes.py`
   - Input: `../data/summary`
   - Output: `../data/embeddings/embedding_bge_m3_<DEFAULT_MODE>`
   - Change `DEFAULT_MODE` in the script before running when needed.
   - Modes: `all_nodes`, `leaf`, `table`, `hybrid`.
   - `all_nodes`: embed every tree node from `all_nodes.json`.
   - `leaf`: embed leaf nodes from `all_leaf_nodes.json`; text includes ancestor context.
   - `table`: embed table chunks from `all_table_chunks.json`.
   - `hybrid`: embed structured text plus table chunks.

3. `04_batch_rag_answers.py`
   - Input: question Excel plus embeddings.
   - Output: answer CSV.
   - Requires local Ollama when generating answers.

4. `app.py` at project root, not in this folder
   - Interactive Streamlit UI.
   - Uses embeddings under `../data/embeddings`.



## 800200 Baseline

`03_embed_fixed_800_200_baseline.py` is separate from structured embedding.

- Input: `../../../../04_Markdown精修區/法規資料_md`
- Output: `../data/embeddings/embedding_bge_m3_800200`
- Chunk size: 800 characters.
- Chunk overlap: 200 characters.
- Step size: 600 characters.
- It does not read `../data/summary`.
- It does not require running `01_build_structured_json.py`.
- Use it to compare fixed-size retrieval against structured legal-node retrieval.

## Mode Ownership

- `01_build_structured_json.py` has no mode switch. It always writes all structured JSON families.
- `02_embed_structured_modes.py` owns structured mode switching via `DEFAULT_MODE`.
- `03_embed_fixed_800_200_baseline.py` owns the fixed 800/200 baseline and has no structured mode.

## Do Not

- Do not run all scripts blindly.
- Do not regenerate embeddings before confirming `DEFAULT_MODE`.
- Do not treat `table_audit_tool.py` as required for the main pipeline.
