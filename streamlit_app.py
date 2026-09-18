from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import requests
import streamlit as st


st.set_page_config(
    page_title="ASTK Studio",
    page_icon="A",
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT_BACKEND_URL = "http://127.0.0.1:4173"
ACTIVE_STATUSES = {"queued", "running"}
TERMINAL_STATUSES = {"completed", "failed"}
SPECIES = (
    "Mus musculus · mm10",
    "Homo sapiens · hg38",
    "Drosophila melanogaster · dm6",
    "Caenorhabditis elegans · ce11",
    "Arabidopsis thaliana · TAIR10",
)
DATA_SOURCES = (
    "Salmon quant.sf · transcript TPM",
    "SUPPA2 PSI / dPSI",
    "rMATS results",
)
DESIGNS = ("多时间点发育序列", "两组比较", "多组比较")
EVENT_LABELS = {
    "A3": "Alternative 3' splice site",
    "A5": "Alternative 5' splice site",
    "AF": "Alternative first exon",
    "AL": "Alternative last exon",
    "MX": "Mutually exclusive exons",
    "RI": "Retained intron",
    "SE": "Skipped exon",
}

DEMO_RESULTS = {
    "metrics": {
        "total_events": 42817,
        "significant_events": 1824,
        "sample_count": 6,
        "median_abs_dpsi": 0.27,
    },
    "event_counts": {"A3": 3851, "A5": 3425, "AF": 9848, "AL": 4282, "MX": 2141, "RI": 5994, "SE": 13276},
    "significant_event_counts": {"A3": 158, "A5": 132, "AF": 409, "AL": 186, "MX": 91, "RI": 247, "SE": 601},
    "direction_counts": {"up": 947, "down": 877},
    "events": [
        ["ENSMUSG00000025900.13;SE:chr1:4293012-4311270", "Ttn", "SE", "E11.5 -> E16.5", "0.82", "+0.46", "2.1e-08"],
        ["ENSMUSG00000033845.7;AF:chr7:127883-130112", "Mef2c", "AF", "E11.5 -> E16.5", "0.18", "-0.39", "8.4e-07"],
        ["ENSMUSG00000067274.6;RI:chr5:991233-994814", "Ryr2", "RI", "E12.5 -> P0", "0.67", "+0.34", "1.7e-05"],
        ["ENSMUSG00000037742.8;A3:chr9:214221-216087", "Actc1", "A3", "E11.5 -> E13.5", "0.41", "-0.31", "3.2e-05"],
        ["ENSMUSG00000029661.12;SE:chr2:663102-667720", "Nrxn1", "SE", "E13.5 -> E16.5", "0.75", "+0.29", "6.8e-05"],
        ["ENSMUSG00000022514.10;AL:chr8:772891-776230", "Pkm", "AL", "E11.5 -> P0", "0.29", "-0.28", "9.4e-05"],
        ["ENSMUSG00000022454.14;A5:chr11:401992-405381", "Srsf3", "A5", "E12.5 -> E15.5", "0.63", "+0.25", "1.2e-04"],
        ["ENSMUSG00000020186.9;MX:chr3:918221-923145", "Mbnl1", "MX", "E13.5 -> E16.5", "0.52", "-0.22", "2.7e-04"],
    ],
    "images": {},
    "comparisons": [{"control": "E11.5", "treatment": "E16.5", "label": "E11.5 -> E16.5"}],
    "reference": {"id": "mm10-gencode-m25"},
    "mode": "demo",
}


st.markdown(
    """
    <style>
      .block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
      .astk-hero {
        border: 1px solid #d8e5de;
        border-radius: 8px;
        padding: 22px 24px;
        background: linear-gradient(120deg, #f3faf6 0%, #fffaf6 100%);
        margin-bottom: 18px;
      }
      .astk-hero h1 { margin: 0; color: #173b2f; font-size: 2rem; letter-spacing: 0; }
      .astk-hero p { margin: 8px 0 0; color: #557067; }
      .astk-kicker {
        color: #2f7a61;
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }
      .astk-status {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 5px 9px;
        border-radius: 999px;
        background: #e8f6ef;
        color: #27624e;
        font-size: 0.78rem;
        font-weight: 600;
      }
      .astk-status.offline { background: #fff4db; color: #8a6419; }
      .astk-status-dot { width: 7px; height: 7px; border-radius: 50%; background: #2f9b70; }
      .astk-status.offline .astk-status-dot { background: #d49a2a; }
      div[data-testid="stMetric"] {
        border: 1px solid #dce7e1;
        border-radius: 8px;
        padding: 12px 14px;
        background: #ffffff;
      }
      div[data-testid="stMetricLabel"] { color: #62756d; }
      .stTabs [data-baseweb="tab-list"] { gap: 6px; }
      .stTabs [data-baseweb="tab"] { border-radius: 6px 6px 0 0; }
    </style>
    """,
    unsafe_allow_html=True,
)


def setting(name: str, default: str | None = None) -> str | None:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return str(value) if value not in (None, "") else os.getenv(name, default)


def backend_url() -> str:
    return (
        st.session_state.get("astk_backend_url")
        or setting("ASTK_BACKEND_URL", DEFAULT_BACKEND_URL)
        or DEFAULT_BACKEND_URL
    ).rstrip("/")


def api_url(path: str) -> str:
    return f"{backend_url()}{path}"


def request_json(method: str, path: str, *, timeout: float = 20, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, api_url(path), timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"无法连接后端 {backend_url()}：{exc}") from exc
    if not response.ok:
        detail = response.text.strip()
        try:
            payload = response.json()
            detail = payload.get("error") or payload.get("detail") or detail
        except ValueError:
            pass
        raise RuntimeError(detail or f"Backend returned HTTP {response.status_code}")
    return response.json()


def health() -> dict[str, Any] | None:
    try:
        return request_json("GET", "/api/health", timeout=6)
    except Exception:
        return None


def create_job(config: dict[str, Any], uploaded_files: list[Any]) -> dict[str, Any]:
    files = []
    for uploaded in uploaded_files:
        files.append(
            (
                "files",
                (
                    uploaded.name,
                    uploaded.getvalue(),
                    uploaded.type or "application/octet-stream",
                ),
            )
        )
    return request_json(
        "POST",
        "/api/jobs",
        data={"config": json.dumps(config, ensure_ascii=False)},
        files=files,
        timeout=120,
    )


def fetch_job(job_id: str) -> dict[str, Any] | None:
    try:
        return request_json("GET", f"/api/jobs/{job_id}", timeout=15)
    except RuntimeError:
        return None


def fetch_results(job_id: str) -> dict[str, Any] | None:
    try:
        return request_json("GET", f"/api/jobs/{job_id}/results", timeout=30)
    except RuntimeError:
        return None


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_bytes(url: str) -> bytes | None:
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        return response.content
    except requests.RequestException:
        return None


def format_number(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def status_badge(online: bool, mode: str = "") -> None:
    klass = "" if online else " offline"
    text = "后端已连接" if online else "等待配置后端"
    if online and mode:
        text = f"后端已连接 · {mode}"
    st.markdown(
        f'<span class="astk-status{klass}"><span class="astk-status-dot"></span>{text}</span>',
        unsafe_allow_html=True,
    )


def render_metrics(results: dict[str, Any]) -> None:
    metrics = results.get("metrics", {})
    columns = st.columns(4)
    columns[0].metric("Detected events", format_number(metrics.get("total_events", 0)))
    columns[1].metric("Significant events", format_number(metrics.get("significant_events", 0)))
    columns[2].metric("Samples", format_number(metrics.get("sample_count", 0)))
    columns[3].metric("Median |dPSI|", f"{float(metrics.get('median_abs_dpsi', 0)):.2f}")


def render_event_table(results: dict[str, Any]) -> None:
    events = results.get("events", [])
    if not events:
        st.info("当前结果中没有可显示的事件。")
        return
    columns = ["event_id", "gene", "type", "comparison", "psi", "dPSI", "p-value"]
    rows = []
    for row in events:
        if isinstance(row, dict):
            values = row
            rows.append({column: values.get(column, "") for column in columns})
        elif isinstance(row, (list, tuple)):
            padded = list(row) + [""] * (len(columns) - len(row))
            rows.append(dict(zip(columns, padded[: len(columns)])))
    st.dataframe(rows, width="stretch", hide_index=True)


def render_images(results: dict[str, Any], job_id: str) -> None:
    images = results.get("images") or {}
    if not images:
        st.info("本次分析结果中没有图片文件。完成真实 ASTK 任务后会在此展示 PCA、热图、火山图、柱状图和 UpSet 图。")
        return
    category_labels = {
        "bar": "Event counts",
        "pca": "PCA",
        "heatmap": "Heatmap",
        "volcano": "Volcano",
        "upset": "UpSet",
    }
    for category, items in images.items():
        st.subheader(category_labels.get(category, category.title()))
        columns = st.columns(2)
        for index, item in enumerate(items):
            path = item.get("path", "")
            image_url = api_url(f"/api/jobs/{job_id}/files/{path}")
            image = fetch_bytes(image_url)
            with columns[index % 2]:
                if image:
                    st.image(image, caption=item.get("name", path))
                else:
                    st.warning(f"图片加载失败：{item.get('name', path)}")


def render_download(results: dict[str, Any], job_id: str) -> None:
    st.write("下载完整分析结果，包括任务配置、ASTK 元数据、结果 JSON、图表和运行日志。")
    archive = fetch_bytes(api_url(f"/api/jobs/{job_id}/download"))
    if archive:
        st.download_button(
            "下载完整报告 ZIP",
            data=archive,
            file_name=f"{job_id}-astk-report.zip",
            mime="application/zip",
            type="primary",
        )
    else:
        st.info("报告还在生成中，任务完成后可下载。")
    st.caption(f"任务编号：{job_id}")


def render_results(job_id: str, results: dict[str, Any] | None) -> None:
    if not results:
        st.info("结果尚未生成。任务完成后请刷新或等待自动刷新。")
        return
    render_metrics(results)
    tabs = st.tabs(["结果概览", "事件浏览器", "图表", "结果下载"])
    with tabs[0]:
        st.subheader("Comparison groups")
        comparisons = results.get("comparisons") or []
        if comparisons:
            labels = [item.get("label") or f'{item.get("control", "")} -> {item.get("treatment", "")}' for item in comparisons]
            st.write(" · ".join(labels))
        else:
            st.caption("未返回比较组标签。")
        st.subheader("Event classes")
        counts = results.get("event_counts") or {}
        chart_rows = [{"type": key, "label": EVENT_LABELS.get(key, key), "count": value} for key, value in counts.items()]
        st.dataframe(chart_rows, width="stretch", hide_index=True)
        directions = results.get("direction_counts") or {}
        up, down = st.columns(2)
        up.metric("Up", format_number(directions.get("up", 0)))
        down.metric("Down", format_number(directions.get("down", 0)))
    with tabs[1]:
        render_event_table(results)
    with tabs[2]:
        render_images(results, job_id)
    with tabs[3]:
        render_download(results, job_id)


def render_job_panel(job_id: str) -> dict[str, Any] | None:
    job = fetch_job(job_id)
    if not job:
        st.error(f"无法读取任务 {job_id}。请检查后端地址和任务编号。")
        return None
    status = job.get("status", "unknown")
    progress = max(0, min(100, int(job.get("progress") or 0)))
    stage = job.get("stage") or "等待中"
    st.subheader(f"任务 {job_id}")
    st.progress(progress / 100.0)
    st.caption(f"{status} · {stage} · {progress}%")
    if job.get("error"):
        st.error(str(job["error"]))
    results = None
    if status == "completed":
        results = fetch_results(job_id)
        st.session_state["astk_results"] = results
    render_results(job_id, results if results is not None else st.session_state.get("astk_results"))
    return job


@st.fragment(run_every=3.0)
def render_live_job(job_id: str) -> None:
    job = render_job_panel(job_id)
    if job and job.get("status") in TERMINAL_STATUSES:
        st.rerun(scope="app")


st.markdown(
    """
    <div class="astk-hero">
      <div class="astk-kicker">ASTK Studio · Streamlit front end</div>
      <h1>可变剪切分析工作台</h1>
      <p>上传转录本定量 ZIP 和样本表，提交到 Linux ASTK 服务，查看七类事件和下游图表。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

if "astk_backend_url" not in st.session_state:
    st.session_state["astk_backend_url"] = setting("ASTK_BACKEND_URL", DEFAULT_BACKEND_URL) or DEFAULT_BACKEND_URL

with st.sidebar:
    st.markdown("## ASTK Studio")
    st.caption("固定前端地址 · 远程计算后端")
    configured_backend = setting("ASTK_BACKEND_URL")
    st.text_input(
        "后端地址",
        key="astk_backend_url",
        disabled=bool(configured_backend),
        help="部署到 Streamlit Cloud 时，在 Secrets 中设置 ASTK_BACKEND_URL。",
    )
    current_health = health()
    status_badge(current_health is not None, (current_health or {}).get("execution_mode", ""))
    if st.button("检测连接", use_container_width=True):
        st.rerun()
    st.divider()
    st.markdown("### 查询已有任务")
    lookup_id = st.text_input("任务编号", placeholder="ASTK-260918-123456-ABCD")
    if st.button("加载任务", use_container_width=True) and lookup_id.strip():
        st.session_state["astk_job_id"] = lookup_id.strip()
        st.session_state.pop("astk_results", None)
        st.rerun()
    st.divider()
    st.caption("计算任务通常需要较长时间。Streamlit 只负责界面，ASTK 在 Linux 后端继续运行。")

current_health = health()
if current_health is None:
    st.warning("当前未连接 ASTK 后端。可以先查看页面结构，配置后端地址后再提交真实任务。")

upload_col, config_col = st.columns([1.15, 0.85], gap="large")
with upload_col:
    st.subheader("01 / 输入文件")
    st.caption("上传一个 ZIP 数据包和一个 CSV 样本表。CSV 文件名可以保持 samples.csv，不需要改名。")
    with st.form("astk_submit_form", clear_on_submit=False):
        uploaded_files = st.file_uploader(
            "拖入或选择文件",
            type=["zip", "csv"],
            accept_multiple_files=True,
            help="ZIP 中包含每个样本的 quant.sf；CSV 中使用现有 samples.csv 列格式。",
        )
        submit = st.form_submit_button("运行 ASTK 分析", type="primary", width="stretch")
    if submit:
        files = uploaded_files or []
        zips = [item for item in files if item.name.lower().endswith(".zip")]
        csvs = [item for item in files if item.name.lower().endswith(".csv")]
        if len(zips) != 1 or len(csvs) != 1:
            st.error("请选择一个 ZIP 数据包和一个 CSV 样本表。")
        elif current_health is None:
            st.error("后端未连接，无法提交任务。")
        else:
            config = {
                "data_source": st.session_state.get("data_source", DATA_SOURCES[0]),
                "species": st.session_state.get("species", SPECIES[0]),
                "design": st.session_state.get("design", DESIGNS[0]),
                "comparison_mode": "baseline",
                "event_type": "ALL",
                "method": "empirical",
                "p_value": float(st.session_state.get("p_value", 0.05)),
                "abs_dpsi": 0.1,
                "demo": False,
                "files": [item.name for item in files],
            }
            with st.spinner("正在提交任务并准备 ASTK 输入..."):
                try:
                    job = create_job(config, files)
                    st.session_state["astk_job_id"] = job["id"]
                    st.session_state.pop("astk_results", None)
                    st.success(f"任务已创建：{job['id']}")
                    st.rerun()
                except Exception as exc:
                    st.error(f"提交失败：{exc}")

with config_col:
    st.subheader("02 / 分析配置")
    st.selectbox("数据来源", DATA_SOURCES, key="data_source")
    st.selectbox("物种和参考注释", SPECIES, key="species")
    st.selectbox("实验设计", DESIGNS, key="design")
    st.number_input("显著性阈值 p-value", min_value=0.0001, max_value=1.0, value=0.05, step=0.01, format="%.4f", key="p_value")
    st.caption("默认使用 |dPSI| >= 0.1，比较模式为 baseline。")

st.divider()
job_id = st.session_state.get("astk_job_id")
if job_id:
    job = fetch_job(job_id)
    if job and job.get("status") in ACTIVE_STATUSES:
        render_live_job(job_id)
    else:
        render_job_panel(job_id)
else:
    st.subheader("结果预览")
    st.caption("这是演示数据，用于预览页面结构。连接后端并提交任务后会替换为真实结果。")
    render_results("DEMO", DEMO_RESULTS)

st.caption(
    "ASTK Studio Streamlit front end · "
    + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
)
