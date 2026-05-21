from __future__ import annotations

import json
import os
import pickle
import re
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import numpy as np
import requests
import streamlit as st
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer

# ── 連結第一部分（同資料夾的preprocessing.py）──
from preprocessing import preprocess

# ── 連結第三部分（同資料夾的prompt_engineering.py）──
from prompt_engineering import build_prompt, generate_answer


ROOT = Path(__file__).resolve().parent
DATA_ROOT = ROOT / "data"
EMBEDDINGS_ROOT = DATA_ROOT / "embeddings"
DEFAULT_MODEL = "BAAI/bge-m3"
DEFAULT_OLLAMA_MODEL = "llama3.1:latest"
AVAILABLE_MODES = ("hybrid", "leaf", "table", "all_nodes", "800200")
HYBRID_TEXT_OPTIONS = ("leaf", "all_nodes")


# ════════════════════════════════════════════
# 原本app.py裡面的
# ════════════════════════════════════════════

def find_available_port(start_port: int = 8501, max_attempts: int = 20) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(
        f"No available port found between {start_port} and {start_port + max_attempts - 1}"
    )


def open_browser_delayed(port: int, delay_seconds: float = 1.5) -> None:
    url = f"http://localhost:{port}"

    def _open() -> None:
        try:
            if os.name == "nt":
                os.startfile(url)
            else:
                webbrowser.open(url)
        except Exception:
            webbrowser.open(url)

    threading.Timer(delay_seconds, _open).start()


if __name__ == "__main__":
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        get_script_run_ctx = None

    if get_script_run_ctx is None or get_script_run_ctx() is None:
        from streamlit.web import cli as stcli

        port = find_available_port()
        print(f"Opening Streamlit at http://localhost:{port}")
        open_browser_delayed(port)
        sys.argv = [
            "streamlit",
            "run",
            str(Path(__file__).resolve()),
            "--server.port",
            str(port),
        ]
        raise SystemExit(stcli.main())


def load_metadata(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line in file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


@st.cache_resource(show_spinner=False)
def load_model(model_name: str) -> SentenceTransformer:
    return SentenceTransformer(model_name)


@st.cache_resource(show_spinner=False)
def load_single_embedding_data(mode: str) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]:
    if mode not in AVAILABLE_MODES:
        raise ValueError(f"Unsupported mode: {mode}")

    embedding_dir = EMBEDDINGS_ROOT / f"embedding_bge_m3_{mode}"
    embedding_path = embedding_dir / "embeddings.npy"
    metadata_path = embedding_dir / "metadata.jsonl"
    summary_path = embedding_dir / "embedding_summary.json"

    if not embedding_path.exists():
        raise FileNotFoundError(f"Missing embeddings file: {embedding_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata file: {metadata_path}")
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing summary file: {summary_path}")

    embeddings = np.load(embedding_path)
    metadata = load_metadata(metadata_path)
    summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))

    if len(embeddings) != len(metadata):
        raise RuntimeError(
            f"Embedding count {len(embeddings)} does not match metadata count {len(metadata)}"
        )

    return embeddings, metadata, summary


@st.cache_resource(show_spinner=False)
def load_embedding_data(mode: str, hybrid_text_mode: str) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]:
    if mode != "hybrid":
        return load_single_embedding_data(mode)

    if hybrid_text_mode not in HYBRID_TEXT_OPTIONS:
        raise ValueError(f"Unsupported hybrid text mode: {hybrid_text_mode}")

    text_embeddings, text_metadata, text_summary = load_single_embedding_data(hybrid_text_mode)
    table_embeddings, table_metadata, table_summary = load_single_embedding_data("table")

    merged_embeddings = np.concatenate([text_embeddings, table_embeddings], axis=0)
    merged_metadata = [*text_metadata, *table_metadata]
    merged_summary = {
        "mode": "hybrid",
        "hybrid_text_mode": hybrid_text_mode,
        "record_count": len(merged_metadata),
        "embedding_dim": int(merged_embeddings.shape[1]) if merged_embeddings.ndim == 2 else None,
        "doc_type_counts": {
            "all_node": sum(1 for row in merged_metadata if row.get("doc_type") == "all_node"),
            "leaf": sum(1 for row in merged_metadata if row.get("doc_type") == "leaf"),
            "table_chunk": sum(1 for row in merged_metadata if row.get("doc_type") == "table_chunk"),
        },
        "sources": {
            "text_mode": hybrid_text_mode,
            "text_metadata": text_summary.get("files", {}).get("metadata"),
            "table_metadata": table_summary.get("files", {}).get("metadata"),
        },
    }
    return merged_embeddings, merged_metadata, merged_summary


def cosine_search(
    query_embedding: np.ndarray,
    doc_embeddings: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    scores = doc_embeddings @ query_embedding
    top_k = min(top_k, len(scores))
    indices = np.argsort(-scores)[:top_k]
    return indices, scores[indices]


def load_ollama_models() -> list[str]:
    try:
        response = requests.get("http://localhost:11434/api/tags", timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception:
        return []
    return [item["name"] for item in data.get("models", []) if item.get("name")]


def build_prompt(question: str, contexts: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for idx, item in enumerate(contexts, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[參考資料 {idx}]",
                    f"類型: {item.get('doc_type', '')}",
                    f"法規檔: {item.get('file_name', '')}",
                    f"路徑: {item.get('path_text', '')}",
                    f"頁碼: {item.get('page_start', '')} - {item.get('page_end', '')}",
                    "內容:",
                    str(item.get("text", "")),
                ]
            )
        )
    return f"""你是法規檢索助理，請只根據提供的內容回答問題，不要自行編造來源。

回答要求:
1. 優先整理與問題最直接相關的資訊。
2. 如果資料不足，直接說明不足，不要硬湊答案。
3. 如有需要，可在答案中引用法規檔名、節點編號或表格位置。
4. 中文字輸出請使用繁體中文。

問題:
{question}

參考資料:
{chr(10).join(blocks)}
"""


def generate_with_ollama(prompt: str, model_name: str) -> str:
    response = requests.post(
        "http://localhost:11434/api/generate",
        json={"model": model_name, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    if "response" not in data:
        raise RuntimeError(f"Ollama 回傳格式異常: {data}")
    return str(data["response"]).strip()


def render_table_location(payload: dict[str, Any]) -> str:
    return (
        f"{payload.get('table_id', '')} / "
        f"r{payload.get('row_index', '')} / "
        f"c{payload.get('col_index', '')} / "
        f"k{payload.get('chunk_index', '')}"
    )


def render_extra_info(item: dict[str, Any]) -> str:
    payload = item.get("payload", {})
    if item.get("doc_type") == "fixed_chunk_800_200":
        return "\n".join(
            [
                f"file_name: {item.get('file_name', '')}",
                f"chunk_index: {payload.get('chunk_index', '')}",
                f"char_range: {payload.get('char_start', '')} - {payload.get('char_end', '')}",
                f"page_range: {item.get('page_start', '')} - {item.get('page_end', '')}",
            ]
        )
    if item.get("doc_type") == "table_chunk":
        return "\n".join(
            [
                f"法規檔：{payload.get('file_name', '')}",
                f"節點編號：{payload.get('under_path_key', '')}",
                f"表格位置：{render_table_location(payload)}",
                f"頁碼：{item.get('page_start', '')} - {item.get('page_end', '')}",
                f"原始 Cell：{payload.get('original_cell_text', '')}",
            ]
        )
    if item.get("doc_type") == "all_node":
        return "\n".join(
            [
                f"法規檔：{item.get('file_name', '')}",
                f"節點名稱：{payload.get('node_name', '')}",
                f"節點編號：{payload.get('path_key', '')}",
                f"節點路徑：{item.get('path_text', '')}",
                f"頁碼：{item.get('page_start', '')} - {item.get('page_end', '')}",
            ]
        )

    context_chain = payload.get("context_chain", [])
    title_chain = " > ".join(
        part
        for row in context_chain
        if isinstance(row, dict)
        for part in [str(row.get("node_name", "")).strip()]
        if part
    )
    return "\n".join(
        [
            f"法規檔：{item.get('file_name', '')}",
            f"標題鏈：{title_chain}",
            f"節點編號：{payload.get('path_key', '')}",
            f"頁碼：{item.get('page_start', '')} - {item.get('page_end', '')}",
        ]
    )


# ════════════════════════════════════════════
# BM25 關鍵字檢索：rank_bm25 + 2-gram tokenize
#
# 1. 2-gram tokenize 避免單字元對任何中文都給高分
# 2. 索引存成 .pkl，重啟 app 不用重建
# ════════════════════════════════════════════

def _tokenize_2gram(text: str) -> list[str]:
    """
    2-gram 切詞：'資訊安全' → ['資訊', '訊安', '安全']
    比單字元有更好的 IDF 鑑別力，避免無關問題拿到高 BM25 分數
    """
    return [text[i:i + 2] for i in range(len(text) - 1)]


def _bm25_cache_path(mode: str, hybrid_text_mode: str) -> Path:
    """BM25 索引的 .pkl 儲存路徑，依模式命名"""
    return DATA_ROOT / f"bm25_index_{mode}_{hybrid_text_mode}.pkl"


@st.cache_resource(show_spinner=False)
def load_bm25_index(mode: str, hybrid_text_mode: str, metadata: tuple) -> BM25Okapi:
    """
    優先從 .pkl 讀取 BM25 索引；若不存在則建立並儲存。
    使用 @st.cache_resource 確保同一 session 只建立一次。
    metadata 傳 tuple 讓 Streamlit cache 能正確比對。
    """
    cache_path = _bm25_cache_path(mode, hybrid_text_mode)

    if cache_path.exists():
        with cache_path.open("rb") as f:
            return pickle.load(f)

    # metadata 在這裡是 tuple[str, ...]（純文字，已在呼叫端取出）
    corpus = [_tokenize_2gram(text) for text in metadata]
    bm25 = BM25Okapi(corpus)

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    with cache_path.open("wb") as f:
        pickle.dump(bm25, f)

    return bm25


def _query_bm25_scores(keywords: list[str], bm25: BM25Okapi) -> np.ndarray:
    """
    用 keywords（2~8 字詞組）查 BM25，query 也用 2-gram 切。
    回傳分數陣列（長度 = 文件數）。
    """
    query_tokens = []
    for kw in keywords:
        query_tokens.extend(_tokenize_2gram(kw))
    query_tokens = list(set(query_tokens))  # 去重

    if not query_tokens:
        return np.zeros(bm25.corpus_size, dtype=np.float32)

    return bm25.get_scores(query_tokens).astype(np.float32)


# ════════════════════════════════════════════
# run_search：正規化 + 混合搜索
#
# 相對app.py的更動：
#   - question → preprocess() 正規化 → combined_query（一次 encode）
#   - 向量 cosine + BM25（rank_bm25，2-gram）加權合併
#   - 向量門檻 VECTOR_THRESHOLD：原始 cosine 過低直接排除，
#     避免「今天早餐吃什麼」拿到高混合分數
#   - 輸出格式與原版完全相同（rank / score / ...item）
# ════════════════════════════════════════════

VECTOR_THRESHOLD = 0.2   # 原始 cosine 低於此值視為不相關


def run_search(
    question: str,
    model: SentenceTransformer,
    doc_embeddings: np.ndarray,
    metadata: list[dict[str, Any]],
    bm25: BM25Okapi,
    top_k: int,
    alpha: float = 0.5,   # 向量權重；1-alpha = BM25 權重
) -> list[dict[str, Any]]:
    """
    混合搜索主流程：
      1. preprocess() 正規化問題 → combined_query + keywords
      2. 單次 encode（CPU 優化：子問題合併後只 encode 一次）
      3. BM25 關鍵字分數（rank_bm25，2-gram）
      4. 向量門檻過濾 → 正規化 → 加權合併
      5. 回傳 top_k，格式與原版相同
    """
    # ── Step 1：前處理 ─────────────────────────────────
    question_b = preprocess({"raw_text": question.strip()})
    combined_query = " ".join(question_b["sub_questions"])  # 子問題合併成一個字串
    keywords = question_b["keywords"]

    # ── Step 2：向量搜索（單次 encode）────────────────
    query_embedding = model.encode(
        [combined_query],          # 只傳一筆，CPU 上最快
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0].astype(np.float32)

    vector_scores: np.ndarray = doc_embeddings @ query_embedding   # cosine, shape (N,)

    # ── Step 3：BM25 關鍵字分數 ───────────────────────
    bm25_scores: np.ndarray = _query_bm25_scores(keywords, bm25)

    # ── Step 4：門檻過濾 + 正規化 + 加權合併 ──────────
    valid_mask = vector_scores >= VECTOR_THRESHOLD  # 絕對門檻

    v_max = float(vector_scores[valid_mask].max()) if valid_mask.any() else 1.0
    k_max = float(bm25_scores.max()) or 1.0

    v_norm = vector_scores / v_max
    k_norm = bm25_scores / k_max

    hybrid: np.ndarray = alpha * v_norm + (1 - alpha) * k_norm
    hybrid[~valid_mask] = 0.0   # 門檻以下歸零，不會出現在結果裡

    # ── Step 5：取 top_k ────────────────────────────────
    top_k_actual = min(top_k, len(hybrid))
    indices = np.argsort(-hybrid)[:top_k_actual]

    results: list[dict[str, Any]] = []
    for rank, idx in enumerate(indices, start=1):
        if hybrid[idx] <= 0.0:
            break   # 門檻以下的不回傳
        item = metadata[int(idx)]
        results.append({
            "rank": rank,
            "score": float(hybrid[idx]),
            "vector_score": float(v_norm[idx]),
            "keyword_score": float(k_norm[idx]),
            "preprocessed_query": combined_query,
            **item,
        })

    return results


# ════════════════════════════════════════════
# UI（下面沒有什麼改，我只有在 expander 裡加兩行分數顯示）
# ════════════════════════════════════════════

if "search_results" not in st.session_state:
    st.session_state.search_results = []
if "search_question" not in st.session_state:
    st.session_state.search_question = ""
if "ollama_answer" not in st.session_state:
    st.session_state.ollama_answer = ""
if "question_input" not in st.session_state:
    st.session_state.question_input = ""
if "submitted_query" not in st.session_state:
    st.session_state.submitted_query = ""
if "prompt_used" not in st.session_state:       # 新增：儲存實際送出的 prompt
    st.session_state.prompt_used = ""
if "question_b" not in st.session_state:        # 新增：儲存前處理結果
    st.session_state.question_b = {}


st.set_page_config(page_title="法規檢索", layout="wide")
st.title("法規檢索")
st.caption("支援 leaf / table / hybrid embedding 查詢")

with st.sidebar:
    model_name = st.text_input("Embedding 模型", value=DEFAULT_MODEL)
    mode = st.selectbox("Embedding 模式", options=list(AVAILABLE_MODES), index=0)
    hybrid_text_mode = st.selectbox(
        "隨便模式法條來源",
        options=list(HYBRID_TEXT_OPTIONS),
        index=0,
        disabled=mode != "hybrid",
    )
    top_k = st.slider("顯示前幾筆", 1, 20, 5)
    # ── 新增：混合搜索權重調整（sidebar 新增一個 slider）──
    alpha = st.slider(
        "向量 / 關鍵字 權重（越高越偏向量）",
        min_value=0.0,
        max_value=1.0,
        value=0.5,
        step=0.05,
    )
    use_ollama = st.checkbox("用 Ollama 整理回答", value=False)
    ollama_models = load_ollama_models()
    if ollama_models:
        default_model = DEFAULT_OLLAMA_MODEL if DEFAULT_OLLAMA_MODEL in ollama_models else ollama_models[0]
        ollama_model = st.selectbox(
            "Ollama 模型",
            ollama_models,
            index=ollama_models.index(default_model),
            disabled=not use_ollama,
        )
    else:
        ollama_model = st.text_input("Ollama 模型", value=DEFAULT_OLLAMA_MODEL, disabled=not use_ollama)

try:
    doc_embeddings, metadata, summary = load_embedding_data(mode, hybrid_text_mode)
except Exception as exc:
    st.error(f"載入 embedding 失敗: {exc}")
    st.stop()

try:
    model = load_model(model_name)
except Exception as exc:
    st.error(f"載入模型失敗: {exc}")
    st.stop()

# BM25 索引：第一次建立後存 .pkl，之後直接讀
try:
    with st.spinner("載入 BM25 關鍵字索引..."):
        bm25 = load_bm25_index(
            mode,
            hybrid_text_mode,
            tuple(str(item.get("text", "")) for item in metadata),
        )
except Exception as exc:
    st.error(f"建立 BM25 索引失敗: {exc}")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("資料筆數", f"{len(metadata):,}")
col2.metric("向量維度", str(doc_embeddings.shape[1]))
col3.metric("模式", summary.get("mode", mode))

if mode == "hybrid":
    st.caption(f"隨便模式的法條文字來源：{hybrid_text_mode}")

with st.expander("embedding 摘要"):
    st.json(summary)

with st.form("search_form", clear_on_submit=False):
    question = st.text_area(
        "問題",
        key="question_input",
        height=100,
        placeholder="例如：資訊安全管理有哪些重點？",
    )
    submitted = st.form_submit_button("開始搜尋", type="primary")

if submitted:
    submitted_query = st.session_state.question_input.strip()
    st.session_state.submitted_query = submitted_query
    st.session_state.search_question = submitted_query
    st.session_state.search_results = []
    st.session_state.ollama_answer = ""
    st.session_state.prompt_used = ""
    st.session_state.question_b = {}

    if submitted_query:
        # ── Step 1：混合搜索（retrieval_real 輸出）────────
        with st.spinner("搜尋中..."):
            # run_search 內部已呼叫 preprocess()，
            # 把 question_b 一起存下來，不重複計算
            from preprocessing import preprocess as _preprocess
            st.session_state.question_b = _preprocess({"raw_text": submitted_query})

            st.session_state.search_results = run_search(
                submitted_query,
                model,
                doc_embeddings,
                metadata,
                bm25,
                top_k,
                alpha,
            )

        # ── Step 2：提示詞工程 → Ollama ───────────────────
        # candidates 直接用 retrieval_real 的輸出，不經動態搜索補齊
        if use_ollama and st.session_state.search_results:
            with st.spinner("組裝 Prompt，呼叫 Ollama 中..."):
                try:
                    result = generate_answer(
                        question_a={"raw_text": submitted_query},
                        question_b=st.session_state.question_b,
                        candidates=st.session_state.search_results,  # 直接用檢索結果
                        relation_notes="",   # 之後由其他組員模組傳入
                        model_name=ollama_model,
                    )
                    st.session_state.ollama_answer = result["answer"]
                    st.session_state.prompt_used = result["prompt"]
                except Exception as exc:
                    st.session_state.ollama_answer = ""
                    st.error(f"Ollama 生成失敗: {exc}")
    else:
        st.session_state.search_results = []

if st.session_state.search_results:
    st.subheader("搜尋結果")
    st.caption(f"目前問題：{st.session_state.search_question}")
    st.caption(f"實際送出：{st.session_state.submitted_query}")

    # 顯示前處理後的查詢（debug 用，可刪）
    if st.session_state.search_results:
        preprocessed = st.session_state.search_results[0].get("preprocessed_query", "")
        if preprocessed:
            st.caption(f"前處理後查詢：{preprocessed}")

    query_key = st.session_state.submitted_query or "empty"
    for item in st.session_state.search_results:
        title = f"{item['rank']}. score={item['score']:.4f} | {item.get('file_name', '')} | {item.get('doc_type', '')}"
        source_key = str(item.get("source_id", item["rank"]))
        widget_key = f"{query_key}_{item['rank']}_{source_key}"
        with st.expander(title, expanded=item["rank"] == 1):
            # ── 新增：顯示混合分數細節（兩行，不影響原本 text_area）──
            st.caption(
                f"向量分數: {item.get('vector_score', 0):.4f}　"
                f"關鍵字分數: {item.get('keyword_score', 0):.4f}　"
                f"混合分數: {item.get('score', 0):.4f}"
            )
            st.text_area(
                f"emb內容 #{item['rank']}",
                value=str(item.get("text", "")),
                height=180,
                key=f"emb_{widget_key}",
            )
            st.text_area(
                f"其他資訊 #{item['rank']}",
                value=render_extra_info(item),
                height=180,
                key=f"meta_{widget_key}",
            )

if st.session_state.ollama_answer:
    st.subheader("Ollama 回答")
    st.write(st.session_state.ollama_answer)

    # 展開可查看實際送出的 prompt（debug 用）
    if st.session_state.prompt_used:
        with st.expander("查看實際送出的 Prompt（debug）"):
            st.text_area(
                "Prompt",
                value=st.session_state.prompt_used,
                height=400,
                key="prompt_display",
            )
