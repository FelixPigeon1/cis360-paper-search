"""Streamlit UI for the CIS 360 Data Fusion Knowledge System."""

from __future__ import annotations

import io
import os
import pandas as pd
import streamlit as st

from db import (
    DB_PATH,
    SEARCHABLE_ATTRIBUTES,
    classify_csv_bundle_role,
    delete_db,
    get_paper_detail,
    get_stats,
    import_csv,
    import_csv_bundle,
    import_excel,
    init_db,
    normalize_sheet_names,
    query_linkage,
    query_popular_dataset,
    query_uncertainty,
    search_papers_by_attribute,
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


def _search_field_labels() -> list[str]:
    return [label for label, _ in SEARCHABLE_ATTRIBUTES]


def _search_field_key(label: str) -> str:
    for lb, key in SEARCHABLE_ATTRIBUTES:
        if lb == label:
            return key
    return SEARCHABLE_ATTRIBUTES[0][1]


def _render_paper_detail_filtered(
    conn,
    doi: str,
    display_field: str | None,
) -> None:
    """If display_field is None, show full paper detail; else DOI plus only that attribute."""
    detail = get_paper_detail(conn, doi)
    st.markdown(f"**DOI:** `{doi}`")

    if display_field is None:
        st.markdown(f"**Author:** {detail.get('author') or '—'}")
        tab_ds, tab_fm = st.tabs(["Datasets", "Fusion Methods"])
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
        return

    if display_field == "title":
        st.markdown(f"**Title:** {detail.get('title') or '—'}")
    elif display_field == "author":
        st.markdown(f"**Author:** {detail.get('author') or '—'}")
    elif display_field == "doi":
        return
    elif display_field == "data_name":
        rows = detail.get("datasets") or []
        if rows:
            st.dataframe(
                pd.DataFrame([{"data_name": r.get("data_name")} for r in rows]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No dataset names for this paper.")
    elif display_field == "u2":
        rows = detail.get("datasets") or []
        if rows:
            st.dataframe(
                pd.DataFrame([{"u2": r.get("u2")} for r in rows]),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption("No U2 entries for this paper.")
    elif display_field in ("method_name", "description", "u1", "u3"):
        fm_rows = detail.get("methods") or []
        if not fm_rows:
            st.caption("No fusion methods for this paper.")
            return
        col = display_field
        if col == "description":
            st.dataframe(
                pd.DataFrame(
                    [{col: _truncate(m.get(col))} for m in fm_rows]
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.dataframe(
                pd.DataFrame([{col: m.get(col)} for m in fm_rows]),
                use_container_width=True,
                hide_index=True,
            )


def page_home():
    st.title("Data Fusion Database")
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
        return

    st.subheader("Search papers")
    st.caption(
        "Search any text column stored in the knowledge base (papers, datasets, or fusion methods)."
    )

    labels = _search_field_labels()
    r1, r2 = st.columns(2)
    with r1:
        search_in_label = st.selectbox(
            "Search in field",
            labels,
            key="home_search_field",
        )
    with r2:
        show_label = st.selectbox(
            "Show in results (optional)",
            ["All fields"] + labels,
            key="home_show_field",
        )

    keyword = st.text_input(
        "Keyword",
        "",
        placeholder="Type a term to match within the selected field",
        key="home_keyword",
    )

    if not keyword.strip():
        st.caption("Enter a keyword to run the search.")
        return

    try:
        conn = get_conn()
        attr = _search_field_key(search_in_label)
        results = search_papers_by_attribute(conn, attr, keyword)
    except Exception as e:
        st.error(str(e))
        return

    if not results:
        st.info("No papers found. Try a different keyword or field.")
        return

    show_key: str | None
    if show_label == "All fields":
        show_key = None
    else:
        show_key = _search_field_key(show_label)

    for paper in results:
        title = paper.get("title") or "(no title)"
        with st.expander(title):
            _render_paper_detail_filtered(conn, paper["doi"], show_key)


def page_upload():
    st.header("Upload Data")
    st.caption(
        "**Excel:** one `.xlsx` workbook with sheets **DOI**, **Data**, and **Fusion Method** (names matched flexibly). "
        "Import **replaces** rows for DOIs present in that workbook (same as before). "
        "**CSV (single or three files):** data is **merged by DOI** — existing rows are **enriched**: CSV only fills **empty** "
        "fields; values already stored are left unchanged. Child rows match on **(doi, data_name)** and **(doi, method_name)** "
        "so repeat uploads update the same record instead of duplicating."
    )

    uploaded = st.file_uploader(
        "Upload Excel workbook or CSV file(s)",
        type=["xlsx", "csv"],
        accept_multiple_files=True,
    )

    if not uploaded:
        return

    files = list(uploaded) if isinstance(uploaded, (list, tuple)) else [uploaded]

    exts = {os.path.splitext(f.name)[1].lower() for f in files}
    if len(exts) != 1:
        st.error("All files in one upload must be the same type (all `.xlsx` or all `.csv`).")
        return

    ext = next(iter(exts))
    if ext not in (".xlsx", ".csv"):
        st.error("Only `.xlsx` and `.csv` are supported.")
        return

    if ext == ".xlsx":
        if len(files) != 1:
            st.error("Upload exactly one Excel workbook (`.xlsx`).")
            return
        excel_bytes = files[0].getvalue()
        sheet_meta = normalize_sheet_names(excel_bytes)
        if sheet_meta is None:
            st.error("Workbook must contain sheets named DOI, Data, and Fusion Method.")
            return
        doi_title, data_title, fusion_title = sheet_meta

        st.subheader("Sheet Preview")
        try:
            bio_preview = io.BytesIO(excel_bytes)
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

        if st.button("Import into Database", type="primary", key="import_excel"):
            try:
                conn = get_conn()
                summary = import_excel(conn, excel_bytes)
                st.cache_resource.clear()
                st.success(
                    f"Imported: {summary['papers']} papers, "
                    f"{summary['datasets']} datasets, {summary['methods']} methods"
                )
            except Exception as e:
                st.error(str(e))
        return

    # CSV paths
    if len(files) == 3:
        role_to_file: dict[str, object] = {}
        for f in files:
            role = classify_csv_bundle_role(f.name)
            if role is None:
                st.error(
                    f"Unrecognized CSV file name `{f.name}`. "
                    "Use **DOI.csv**, **Data.csv**, and **Fusion Method.csv** (flexible spacing/underscores)."
                )
                return
            if role in role_to_file:
                st.error(
                    f"Two files map to the same table ({role}): "
                    f"`{role_to_file[role].name}` and `{f.name}`."
                )
                return
            role_to_file[role] = f

        if set(role_to_file.keys()) != {"doi", "data", "fusion"}:
            st.error("CSV bundle needs exactly one DOI file, one Data file, and one Fusion Method file.")
            return

        st.subheader("CSV Preview (joined on DOI)")
        try:
            doi_prev = pd.read_csv(
                io.BytesIO(role_to_file["doi"].getvalue()), encoding="utf-8-sig"
            )
            data_prev = pd.read_csv(
                io.BytesIO(role_to_file["data"].getvalue()), encoding="utf-8-sig"
            )
            fusion_prev = pd.read_csv(
                io.BytesIO(role_to_file["fusion"].getvalue()), encoding="utf-8-sig"
            )
        except Exception as e:
            st.error(f"Could not read CSV files for preview: {e}")
            return

        t1, t2, t3 = st.tabs(["DOI", "Data", "Fusion Method"])
        with t1:
            st.caption(role_to_file["doi"].name)
            st.dataframe(doi_prev.head(5), use_container_width=True)
        with t2:
            st.caption(role_to_file["data"].name)
            st.dataframe(data_prev.head(5), use_container_width=True)
        with t3:
            st.caption(role_to_file["fusion"].name)
            st.dataframe(fusion_prev.head(5), use_container_width=True)

        bundle_payload = [(f.name, f.getvalue()) for f in files]

        if st.button("Import into Database", type="primary", key="import_csv_bundle"):
            try:
                conn = get_conn()
                summary = import_csv_bundle(conn, bundle_payload)
                st.cache_resource.clear()
                st.success(
                    f"Imported: {summary['papers']} papers, "
                    f"{summary['datasets']} datasets, {summary['methods']} methods"
                )
            except Exception as e:
                st.error(str(e))
        return

    if len(files) == 1:
        flat_bytes = files[0].getvalue()
        st.subheader("CSV Preview")
        try:
            flat_prev = pd.read_csv(io.BytesIO(flat_bytes), encoding="utf-8-sig")
        except Exception as e:
            st.error(f"Could not read CSV for preview: {e}")
            return

        _chk = flat_prev.copy()
        _chk.columns = _chk.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
        if "doi" not in _chk.columns:
            st.error("Combined CSV must include a **DOI** column.")
            return

        st.dataframe(flat_prev.head(5), use_container_width=True)

        if st.button("Import into Database", type="primary", key="import_csv_flat"):
            try:
                conn = get_conn()
                summary = import_csv(conn, flat_bytes)
                st.cache_resource.clear()
                st.success(
                    f"Imported: {summary['papers']} papers, "
                    f"{summary['datasets']} datasets, {summary['methods']} methods"
                )
            except Exception as e:
                st.error(str(e))
        return

    st.error(
        "For CSV, upload **one** combined file, or **three** files (DOI.csv, Data.csv, Fusion Method.csv)."
    )


def page_queries():
    st.header("Knowledge Queries")

    with st.expander("Linkage Query", expanded=True):
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

    with st.expander("Uncertainty Query", expanded=True):
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

    with st.expander("Popular Dataset Query", expanded=True):
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
    if st.button("Delete & Reset Database", type="primary"):
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
            "Knowledge Queries",
            "Database Management",
        ],
        label_visibility="collapsed",
    )

    if page == "Home / Dashboard":
        page_home()
    elif page == "Upload Data":
        page_upload()
    elif page == "Knowledge Queries":
        page_queries()
    else:
        page_db_mgmt()


if __name__ == "__main__":
    main()
