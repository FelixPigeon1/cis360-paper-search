"""Streamlit UI for the CIS 360 Data Fusion Knowledge System."""

from __future__ import annotations

import io
import os
import pandas as pd
import streamlit as st
import re

from db import (
    DB_PATH,
    delete_db,
    get_paper_detail,
    get_stats,
    normalize_sheet_names,
    import_excel,
    init_db,
    query_linkage,
    query_popular_dataset,
    query_uncertainty,
    search_papers,
)

st.set_page_config(
    page_title="Data Fusion Knowledge System",
    layout="wide",
)


@st.cache_resource
def get_conn():
    return init_db(DB_PATH)


def _truncate(text: str | None, max_len: int = 200) -> str:
    if text is None:
        return ""
    s = str(text)
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def page_home():
    st.title("🔬 CIS 360 — Data Fusion Knowledge System")
    try:
        conn = get_conn()
        stats = get_stats(conn)
    except Exception as e:
        st.error(str(e))
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Papers", stats["papers"])
    c2.metric("Total Datasets", stats["datasets"])
    c3.metric("Total Fusion Methods", stats["methods"])

    if stats["papers"] == 0:
        st.info("No data loaded yet. Go to Upload Data to get started.")


def page_upload():
    st.header("Upload Data")
    uploaded = st.file_uploader("Upload Excel workbook or CSV file", type=["xlsx", "csv"])

    if uploaded is not None:
        data = uploaded.getvalue()

        if normalize_sheet_names(data) == None:
            st.error("Workbook must contain sheets named 'DOI', 'Data', and 'Fusion Method'")
            return
        else:
            doi_title, data_title, fusion_title = normalize_sheet_names(data)
            

        st.session_state["pending_xlsx"] = data

        st.subheader("Sheet Preview")
        try:
            bio_preview = io.BytesIO(data)
            doi_prev = pd.read_excel(bio_preview, sheet_name=doi_title)
            bio_preview.seek(0)
            data_prev = pd.read_excel(bio_preview, sheet_name=data_title)
            bio_preview.seek(0)
            fusion_prev = pd.read_excel(bio_preview, sheet_name=fusion_title)
        except Exception as e:
            st.error(f"Could not read workbook for preview: {e}")
            return

        t1, t2, t3 = st.tabs(["DOI", "Data", "Fusion Method"])
        with t1:
            st.dataframe(doi_prev.head(5), use_container_width=True)
        with t2:
            st.dataframe(data_prev.head(5), use_container_width=True)
        with t3:
            st.dataframe(fusion_prev.head(5), use_container_width=True)

        if st.button("Import into Database", type="primary"):
            try:
                conn = get_conn()
                summary = import_excel(conn, st.session_state["pending_xlsx"])
                st.cache_resource.clear()
                st.success(
                    f"✅ Imported: {summary['papers']} papers, "
                    f"{summary['datasets']} datasets, {summary['methods']} methods"
                )
            except Exception as e:
                st.error(str(e))


def page_search():
    st.header("Search Papers")
    keyword = st.text_input("Search by title, author, or DOI", "")

    if not keyword.strip():
        st.caption("Enter a search term to find papers.")
        return

    try:
        conn = get_conn()
        results = search_papers(conn, keyword)
    except Exception as e:
        st.error(str(e))
        return

    if not results:
        st.info("No papers found. Try a different search term.")
        return

    for paper in results:
        title = paper.get("title") or "(no title)"
        with st.expander(title):
            st.markdown(f"**DOI:** `{paper.get('doi')}`")
            st.markdown(f"**Author:** {paper.get('author') or '—'}")

            detail = get_paper_detail(conn, paper["doi"])
            tab_ds, tab_fm = st.tabs(["📊 Datasets", "⚙️ Fusion Methods"])

            with tab_ds:
                ds_rows = detail.get("datasets") or []
                if ds_rows:
                    st.dataframe(
                        pd.DataFrame(ds_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("No datasets recorded for this paper.")

            with tab_fm:
                fm_rows = detail.get("methods") or []
                if fm_rows:
                    display_fm = []
                    for m in fm_rows:
                        display_fm.append(
                            {
                                "method_name": m.get("method_name"),
                                "u1": m.get("u1"),
                                "u3": m.get("u3"),
                                "description": _truncate(m.get("description")),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(display_fm),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption("No fusion methods recorded for this paper.")


def page_queries():
    st.header("Knowledge Queries")

    with st.expander("🔗 Linkage Query", expanded=True):
        st.caption(
            "Find all fusion methods applied to papers that use both Dataset A and Dataset B"
        )
        c1, c2 = st.columns(2)
        with c1:
            da = st.text_input("Dataset A name", key="link_a")
        with c2:
            dataset_b = st.text_input("Dataset B name", key="link_b")
        if st.button("Search", key="link_search"):
            try:
                conn = get_conn()
                rows = query_linkage(conn, da, dataset_b)
                if not rows:
                    st.info("No matching fusion methods found.")
                else:
                    st.dataframe(
                        pd.DataFrame(rows),
                        use_container_width=True,
                        hide_index=True,
                    )
            except Exception as e:
                st.error(str(e))

    with st.expander("⚠️ Uncertainty Query", expanded=True):
        st.caption(
            "Find all papers reporting a specific uncertainty type for a given sensor/keyword"
        )
        umap = {
            "U1 – Conception": "U1",
            "U2 – Measurement": "U2",
            "U3 – Analysis": "U3",
        }
        choice = st.selectbox(
            "Uncertainty Type",
            list(umap.keys()),
        )
        sk = st.text_input("Sensor or keyword to search", key="unc_kw")
        if st.button("Search", key="unc_search"):
            try:
                conn = get_conn()
                rows = query_uncertainty(conn, umap[choice], sk)
                if not rows:
                    st.info("No matching papers found.")
                else:
                    out = []
                    for r in rows:
                        out.append(
                            {
                                "Paper Title": r.get("title"),
                                "Author": r.get("author"),
                                "DOI": r.get("doi"),
                                "Uncertainty Text": r.get("uncertainty_text"),
                            }
                        )
                    st.dataframe(
                        pd.DataFrame(out),
                        use_container_width=True,
                        hide_index=True,
                    )
            except Exception as e:
                st.error(str(e))

    with st.expander("🏆 Popular Dataset Query", expanded=True):
        st.caption("Which dataset appears most often across fusion methods?")
        if st.button("Run Query", key="pop_run"):
            try:
                conn = get_conn()
                rows = query_popular_dataset(conn)
                if not rows:
                    st.info("No data available. Import a workbook first.")
                else:
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                    chart_df = df[["data_name", "method_count"]].set_index("data_name")
                    st.bar_chart(chart_df)
            except Exception as e:
                st.error(str(e))


def page_db_mgmt():
    st.header("Database Management")
    abs_path = os.path.abspath(DB_PATH)
    st.markdown(f"**Database file:** `{abs_path}`")

    size = os.path.getsize(abs_path) if os.path.isfile(abs_path) else 0
    st.markdown(f"**File size:** {size:,} bytes")

    st.warning("This will permanently delete all imported data.")
    if st.button("🗑️ Delete & Reset Database", type="primary"):
        try:
            st.cache_resource.clear()
            delete_db(DB_PATH)
            st.success("Database cleared.")
            st.rerun()
        except Exception as e:
            st.error(str(e))

    try:
        conn = get_conn()
        stats = get_stats(conn)
        st.subheader("Row counts")
        st.dataframe(
            pd.DataFrame(
                [
                    {"table": "papers", "rows": stats["papers"]},
                    {"table": "datasets", "rows": stats["datasets"]},
                    {"table": "fusion_methods", "rows": stats["methods"]},
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    except Exception as e:
        st.error(str(e))


def main():
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to",
        [
            "Home / Dashboard",
            "Upload Data",
            "Search Papers",
            "Knowledge Queries",
            "Database Management",
        ],
        label_visibility="collapsed",
    )

    if page == "Home / Dashboard":
        page_home()
    elif page == "Upload Data":
        page_upload()
    elif page == "Search Papers":
        page_search()
    elif page == "Knowledge Queries":
        page_queries()
    else:
        page_db_mgmt()


if __name__ == "__main__":
    main()
