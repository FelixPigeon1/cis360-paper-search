"""SQLite database helpers for the CIS 360 Data Fusion Knowledge System."""

from __future__ import annotations

import io
import os
import sqlite3
from typing import Any
import re

import pandas as pd

DB_PATH = "data_fusion.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE NOT NULL,
    title TEXT,
    author TEXT
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT NOT NULL,
    data_name TEXT,
    u2 TEXT,
    FOREIGN KEY (doi) REFERENCES papers(doi)
);

CREATE TABLE IF NOT EXISTS fusion_methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT NOT NULL,
    method_name TEXT,
    description TEXT,
    u1 TEXT,
    u3 TEXT,
    FOREIGN KEY (doi) REFERENCES papers(doi)
);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    # Streamlit may use the cached connection from different worker threads.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = out.columns.str.strip().str.lower().str.replace(" ", "_", regex=False)
    return out


def _strip_object_cells(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in out.columns:
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].apply(
                lambda x: x.strip() if isinstance(x, str) else x
            )
    return out


def _drop_empty_doi(df: pd.DataFrame) -> pd.DataFrame:
    if "doi" not in df.columns:
        return df.iloc[0:0].copy()
    s = df["doi"]
    mask = s.notna() & (s.astype(str).str.strip() != "") & (s.astype(str) != "nan")
    return df.loc[mask].copy()


def normalize_sheet_names (file_bytes: bytes) -> list[str]:
        
        all_sheets = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None)
        doi_title = None
        data_title = None
        fusion_title = None

        for sheet in list(all_sheets.keys()):
            if doi_title is None:
                match = re.search(r"(?i)^\s*doi\s*$", sheet)
                if match is not None:
                    doi_title = match
                    continue
            if data_title is None:
                match = re.search(r"(?i)^\s*data\s*$", sheet)
                if match is not None:
                    data_title = match
                    continue
            if fusion_title is None:
                match = re.search(r"(?i)^\s*fusion.?method\s*$", sheet)
                if match is not None:
                    fusion_title = match
                    continue
        

        if not all([doi_title, data_title, fusion_title]):
            return None

        return doi_title.group(0), data_title.group(0), fusion_title.group(0)


def _str_or_none(val: Any) -> str | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def _fill_blank(existing: str | None, incoming: Any) -> str | None:
    """If existing text is missing, take CSV; otherwise keep the stored value."""
    if existing is not None and str(existing).strip() != "":
        return str(existing).strip()
    return _str_or_none(incoming)


def _ensure_paper_stub(cur: sqlite3.Cursor, doi: str) -> None:
    """Ensure a papers row exists so FK inserts on datasets / fusion_methods succeed."""
    cur.execute(
        "INSERT OR IGNORE INTO papers (doi, title, author) VALUES (?, NULL, NULL)",
        (doi,),
    )


def _merge_paper_row(cur: sqlite3.Cursor, doi: str, title: Any, author: Any) -> None:
    cur.execute("SELECT title, author FROM papers WHERE doi = ?", (doi,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO papers (doi, title, author) VALUES (?, ?, ?)",
            (
                doi,
                _str_or_none(title),
                _str_or_none(author),
            ),
        )
        return
    et, ea = row[0], row[1]
    nt = _fill_blank(et, title)
    na = _fill_blank(ea, author)
    cur.execute(
        "UPDATE papers SET title = ?, author = ? WHERE doi = ?",
        (nt, na, doi),
    )


def _dataset_key(data_name: Any) -> str:
    return _str_or_none(data_name) or ""


def _merge_dataset_row(cur: sqlite3.Cursor, doi: str, data_name: Any, u2: Any) -> None:
    _ensure_paper_stub(cur, doi)
    key = _dataset_key(data_name)
    cur.execute(
        """
        SELECT id, data_name, u2 FROM datasets
        WHERE doi = ? AND TRIM(IFNULL(data_name, '')) = ?
        """,
        (doi, key),
    )
    existing = cur.fetchone()
    dn_store = _str_or_none(data_name)
    u2_in = _str_or_none(u2)
    if existing:
        rid, dn_old, u2_old = existing[0], existing[1], existing[2]
        dn_new = _fill_blank(dn_old, data_name)
        u2_new = _fill_blank(u2_old, u2)
        cur.execute(
            "UPDATE datasets SET data_name = ?, u2 = ? WHERE id = ?",
            (dn_new, u2_new, rid),
        )
        return
    cur.execute(
        """
        INSERT INTO datasets (doi, data_name, u2)
        VALUES (?, ?, ?)
        """,
        (doi, dn_store, u2_in),
    )


def _method_key(method_name: Any) -> str:
    return _str_or_none(method_name) or ""


def _merge_fusion_row(
    cur: sqlite3.Cursor,
    doi: str,
    method_name: Any,
    description: Any,
    u1: Any,
    u3: Any,
) -> None:
    _ensure_paper_stub(cur, doi)
    key = _method_key(method_name)
    cur.execute(
        """
        SELECT id, method_name, description, u1, u3 FROM fusion_methods
        WHERE doi = ? AND TRIM(IFNULL(method_name, '')) = ?
        """,
        (doi, key),
    )
    existing = cur.fetchone()
    mn_store = _str_or_none(method_name)
    if existing:
        rid, mn_old, d0, u1_old, u3_old = (
            existing[0],
            existing[1],
            existing[2],
            existing[3],
            existing[4],
        )
        mn_new = _fill_blank(mn_old, method_name)
        d_new = _fill_blank(d0, description)
        u1_new = _fill_blank(u1_old, u1)
        u3_new = _fill_blank(u3_old, u3)
        cur.execute(
            """
            UPDATE fusion_methods
            SET method_name = ?, description = ?, u1 = ?, u3 = ?
            WHERE id = ?
            """,
            (mn_new, d_new, u1_new, u3_new, rid),
        )
        return
    cur.execute(
        """
        INSERT INTO fusion_methods (doi, method_name, description, u1, u3)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            doi,
            mn_store,
            _str_or_none(description),
            _str_or_none(u1),
            _str_or_none(u3),
        ),
    )


def classify_csv_bundle_role(filename: str) -> str | None:
    """
    Map a CSV filename to its logical table: doi, data, or fusion.
    Matches DOI.csv, Data.csv, Fusion Method.csv, fusion_method.csv, etc.
    """
    stem = os.path.splitext(os.path.basename(filename))[0].lower().strip()
    stem = re.sub(r"[\s\-]+", "_", stem)
    if stem == "doi":
        return "doi"
    if stem == "data":
        return "data"
    if stem in ("fusion_method", "fusionmethod", "fusion"):
        return "fusion"
    return None


def import_joined_tables(
    conn: sqlite3.Connection,
    doi_df: pd.DataFrame,
    data_df: pd.DataFrame,
    fusion_df: pd.DataFrame,
) -> dict[str, int]:
    """
    Import the three logical tables joined on DOI (same rules as Excel sheets).
    """
    doi_df = _strip_object_cells(_normalize_columns(doi_df))
    data_df = _strip_object_cells(_normalize_columns(data_df))
    fusion_df = _strip_object_cells(_normalize_columns(fusion_df))

    doi_df = _drop_empty_doi(doi_df)
    data_df = _drop_empty_doi(data_df)
    fusion_df = _drop_empty_doi(fusion_df)

    expected_doi = {"doi", "title", "author"}
    expected_data = {"doi", "data_name", "u2"}
    expected_fusion = {"doi", "method_name", "description", "u1", "u3"}

    for col in expected_doi - set(doi_df.columns):
        doi_df[col] = None
    for col in expected_data - set(data_df.columns):
        data_df[col] = None
    for col in expected_fusion - set(fusion_df.columns):
        fusion_df[col] = None

    all_dois: set[str] = set()
    for frame in (doi_df, data_df, fusion_df):
        if len(frame) and "doi" in frame.columns:
            all_dois.update(frame["doi"].dropna().astype(str).str.strip().tolist())

    cur = conn.cursor()
    for doi in all_dois:
        cur.execute("DELETE FROM datasets WHERE doi = ?", (doi,))
        cur.execute("DELETE FROM fusion_methods WHERE doi = ?", (doi,))

    papers_inserted = 0
    for _, row in doi_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        cur.execute(
            """
            INSERT OR IGNORE INTO papers (doi, title, author)
            VALUES (?, ?, ?)
            """,
            (
                str(d).strip(),
                None if pd.isna(row.get("title")) else str(row.get("title")),
                None if pd.isna(row.get("author")) else str(row.get("author")),
            ),
        )
        papers_inserted += 1

    paper_dois = set(
        doi_df["doi"].dropna().astype(str).str.strip().tolist()
    ) if len(doi_df) else set()

    datasets_inserted = 0
    for _, row in data_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        ds = str(d).strip()
        if ds not in paper_dois:
            continue
        cur.execute(
            """
            INSERT INTO datasets (doi, data_name, u2)
            VALUES (?, ?, ?)
            """,
            (
                ds,
                None if pd.isna(row.get("data_name")) else str(row.get("data_name")),
                None if pd.isna(row.get("u2")) else str(row.get("u2")),
            ),
        )
        datasets_inserted += 1

    methods_inserted = 0
    for _, row in fusion_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        fd = str(d).strip()
        if fd not in paper_dois:
            continue
        cur.execute(
            """
            INSERT INTO fusion_methods (doi, method_name, description, u1, u3)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                fd,
                None if pd.isna(row.get("method_name")) else str(row.get("method_name")),
                None if pd.isna(row.get("description")) else str(row.get("description")),
                None if pd.isna(row.get("u1")) else str(row.get("u1")),
                None if pd.isna(row.get("u3")) else str(row.get("u3")),
            ),
        )
        methods_inserted += 1

    conn.commit()
    return {
        "papers": papers_inserted,
        "datasets": datasets_inserted,
        "methods": methods_inserted,
    }


def import_joined_tables_enrich(
    conn: sqlite3.Connection,
    doi_df: pd.DataFrame,
    data_df: pd.DataFrame,
    fusion_df: pd.DataFrame,
) -> dict[str, int]:
    """
    Merge CSV-style data into existing rows by DOI: update/fill blanks, insert only
    when no matching row exists. Does not delete existing dataset or fusion rows.
    """
    doi_df = _strip_object_cells(_normalize_columns(doi_df))
    data_df = _strip_object_cells(_normalize_columns(data_df))
    fusion_df = _strip_object_cells(_normalize_columns(fusion_df))

    doi_df = _drop_empty_doi(doi_df)
    data_df = _drop_empty_doi(data_df)
    fusion_df = _drop_empty_doi(fusion_df)

    expected_doi = {"doi", "title", "author"}
    expected_data = {"doi", "data_name", "u2"}
    expected_fusion = {"doi", "method_name", "description", "u1", "u3"}

    for col in expected_doi - set(doi_df.columns):
        doi_df[col] = None
    for col in expected_data - set(data_df.columns):
        data_df[col] = None
    for col in expected_fusion - set(fusion_df.columns):
        fusion_df[col] = None

    cur = conn.cursor()
    papers_n = 0
    for _, row in doi_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        ds = str(d).strip()
        _merge_paper_row(cur, ds, row.get("title"), row.get("author"))
        papers_n += 1

    datasets_n = 0
    for _, row in data_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        ds = str(d).strip()
        _merge_dataset_row(cur, ds, row.get("data_name"), row.get("u2"))
        datasets_n += 1

    methods_n = 0
    for _, row in fusion_df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        fd = str(d).strip()
        _merge_fusion_row(
            cur,
            fd,
            row.get("method_name"),
            row.get("description"),
            row.get("u1"),
            row.get("u3"),
        )
        methods_n += 1

    conn.commit()
    return {"papers": papers_n, "datasets": datasets_n, "methods": methods_n}


def import_excel(conn: sqlite3.Connection, file_bytes: bytes) -> dict[str, int]:
    bio = io.BytesIO(file_bytes)
    doi_title, data_title, fusion_title = normalize_sheet_names(file_bytes)

    if not all([doi_title, data_title, fusion_title]):
        raise ValueError("Invalid sheet names in the uploaded file")

    doi_df = pd.read_excel(bio, sheet_name=doi_title)
    bio.seek(0)
    data_df = pd.read_excel(bio, sheet_name=data_title)
    bio.seek(0)
    fusion_df = pd.read_excel(bio, sheet_name=fusion_title)

    return import_joined_tables(conn, doi_df, data_df, fusion_df)


def import_csv_bundle(
    conn: sqlite3.Connection, named_files: list[tuple[str, bytes]]
) -> dict[str, int]:
    """
    Import three CSV files (DOI, Data, Fusion Method), joined on DOI.
    Enriches existing rows by DOI instead of replacing child tables; filenames must
    map uniquely to doi / data / fusion (see classify_csv_bundle_role).
    """
    if len(named_files) != 3:
        raise ValueError("CSV bundle import requires exactly three CSV files.")

    roles: dict[str, tuple[str, bytes]] = {}
    for name, b in named_files:
        role = classify_csv_bundle_role(name)
        if role is None:
            raise ValueError(
                f"Unrecognized CSV bundle file name: {name!r}. "
                "Expected names like DOI.csv, Data.csv, and Fusion Method.csv."
            )
        if role in roles:
            raise ValueError(
                f"Duplicate role {role!r}: {name!r} conflicts with {roles[role][0]!r}."
            )
        roles[role] = (name, b)

    missing = {"doi", "data", "fusion"} - set(roles.keys())
    if missing:
        raise ValueError(
            "CSV bundle needs DOI, Data, and Fusion Method tables. "
            f"Missing: {', '.join(sorted(missing))}."
        )

    def _read_csv(raw: bytes) -> pd.DataFrame:
        return pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")

    doi_df = _read_csv(roles["doi"][1])
    data_df = _read_csv(roles["data"][1])
    fusion_df = _read_csv(roles["fusion"][1])

    return import_joined_tables_enrich(conn, doi_df, data_df, fusion_df)


def import_csv(conn: sqlite3.Connection, file_bytes: bytes) -> dict[str, int]:
    """
    Single combined CSV: merge by DOI into papers, datasets, and fusion_methods.
    Existing rows are enriched (non-empty CSV values fill blanks); duplicate
    (doi, data_name) / (doi, method_name) keys update the same row instead of inserting again.
    """
    bio = io.BytesIO(file_bytes)
    df = pd.read_csv(bio)
    df = _strip_object_cells(_normalize_columns(df))
    df = _drop_empty_doi(df)

    expected_cols = {"doi", "title", "author", "data_name", "u2", "method_name", "description", "u1", "u3"}
    for col in expected_cols - set(df.columns):
        df[col] = None

    cur = conn.cursor()
    papers_n = 0
    datasets_n = 0
    methods_n = 0

    for _, row in df.iterrows():
        d = row.get("doi")
        if d is None or str(d).strip() == "":
            continue
        doi_str = str(d).strip()

        _merge_paper_row(cur, doi_str, row.get("title"), row.get("author"))
        papers_n += 1

        has_ds = any(
            _str_or_none(row.get(c)) is not None for c in ("data_name", "u2")
        )
        if has_ds:
            _merge_dataset_row(cur, doi_str, row.get("data_name"), row.get("u2"))
            datasets_n += 1

        has_fm = any(
            _str_or_none(row.get(c)) is not None
            for c in ("method_name", "description", "u1", "u3")
        )
        if has_fm:
            _merge_fusion_row(
                cur,
                doi_str,
                row.get("method_name"),
                row.get("description"),
                row.get("u1"),
                row.get("u3"),
            )
            methods_n += 1

    conn.commit()
    return {"papers": papers_n, "datasets": datasets_n, "methods": methods_n}


def delete_db(db_path: str) -> None:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = init_db(db_path)
    conn.close()


def get_stats(conn: sqlite3.Connection) -> dict[str, int]:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM papers")
    papers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM datasets")
    datasets = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM fusion_methods")
    methods = cur.fetchone()[0]
    return {"papers": papers, "datasets": datasets, "methods": methods}


# User-facing label -> internal key (used for search + optional display filter)
SEARCHABLE_ATTRIBUTES: list[tuple[str, str]] = [
    ("Paper title", "title"),
    ("Author", "author"),
    ("DOI", "doi"),
    ("Dataset name", "data_name"),
    ("U2 — measurement uncertainty", "u2"),
    ("Fusion method name", "method_name"),
    ("Method description", "description"),
    ("U1 — conception uncertainty", "u1"),
    ("U3 — analysis uncertainty", "u3"),
]


def search_papers(conn: sqlite3.Connection, keyword: str) -> list[dict[str, Any]]:
    kw = keyword.strip()
    if not kw:
        return []
    term = f"%{kw}%"
    cur = conn.execute(
        """
        SELECT doi, title, author
        FROM papers
        WHERE title LIKE ? OR author LIKE ? OR doi LIKE ?
        ORDER BY title
        """,
        (term, term, term),
    )
    rows = cur.fetchall()
    return [{"doi": r[0], "title": r[1], "author": r[2]} for r in rows]


def search_papers_by_attribute(
    conn: sqlite3.Connection, attribute: str, keyword: str
) -> list[dict[str, Any]]:
    """Return distinct papers whose chosen text field matches keyword (LIKE %keyword%)."""
    valid = {k for _, k in SEARCHABLE_ATTRIBUTES}
    if attribute not in valid:
        return []
    kw = keyword.strip()
    if not kw:
        return []
    term = f"%{kw}%"

    if attribute == "title":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            WHERE p.title LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "author":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            WHERE p.author LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "doi":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            WHERE p.doi LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "data_name":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN datasets d ON d.doi = p.doi
            WHERE d.data_name LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "u2":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN datasets d ON d.doi = p.doi
            WHERE d.u2 LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "method_name":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN fusion_methods fm ON fm.doi = p.doi
            WHERE fm.method_name LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "description":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN fusion_methods fm ON fm.doi = p.doi
            WHERE fm.description LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "u1":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN fusion_methods fm ON fm.doi = p.doi
            WHERE fm.u1 LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    elif attribute == "u3":
        sql = """
            SELECT DISTINCT p.doi, p.title, p.author FROM papers p
            INNER JOIN fusion_methods fm ON fm.doi = p.doi
            WHERE fm.u3 LIKE ? ORDER BY COALESCE(p.title, ''), p.doi
        """
    else:
        return []

    cur = conn.execute(sql, (term,))
    rows = cur.fetchall()
    return [{"doi": r[0], "title": r[1], "author": r[2]} for r in rows]


def get_paper_detail(conn: sqlite3.Connection, doi: str) -> dict[str, Any]:
    cur = conn.execute(
        "SELECT doi, title, author FROM papers WHERE doi = ?",
        (doi,),
    )
    row = cur.fetchone()
    if not row:
        return {
            "doi": doi,
            "title": None,
            "author": None,
            "datasets": [],
            "methods": [],
        }

    cur = conn.execute(
        "SELECT data_name, u2 FROM datasets WHERE doi = ? ORDER BY id",
        (doi,),
    )
    datasets = [
        {"data_name": r[0], "u2": r[1]}
        for r in cur.fetchall()
    ]

    cur = conn.execute(
        """
        SELECT method_name, description, u1, u3
        FROM fusion_methods
        WHERE doi = ?
        ORDER BY id
        """,
        (doi,),
    )
    methods = [
        {"method_name": r[0], "description": r[1], "u1": r[2], "u3": r[3]}
        for r in cur.fetchall()
    ]

    return {
        "doi": row[0],
        "title": row[1],
        "author": row[2],
        "datasets": datasets,
        "methods": methods,
    }


def query_linkage(
    conn: sqlite3.Connection, dataset_a: str, dataset_b: str
) -> list[dict[str, Any]]:
    a = dataset_a.strip()
    b = dataset_b.strip()
    if not a or not b:
        return []

    pa, pb = f"%{a}%", f"%{b}%"
    cur = conn.execute(
        """
        SELECT DISTINCT fm.method_name, p.title, p.doi
        FROM fusion_methods fm
        JOIN papers p ON p.doi = fm.doi
        WHERE EXISTS (
            SELECT 1 FROM datasets d1
            WHERE d1.doi = fm.doi AND LOWER(d1.data_name) LIKE LOWER(?)
        )
        AND EXISTS (
            SELECT 1 FROM datasets d2
            WHERE d2.doi = fm.doi AND LOWER(d2.data_name) LIKE LOWER(?)
        )
        ORDER BY fm.method_name, p.title
        """,
        (pa, pb),
    )

    rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({"method_name": r[0], "title": r[1], "doi": r[2]})
    return out


def query_uncertainty(
    conn: sqlite3.Connection, uncertainty_type: str, sensor_keyword: str
) -> list[dict[str, Any]]:
    col = {"U1": "u1", "U2": "u2", "U3": "u3"}.get(uncertainty_type)
    if col is None:
        return []
    kw = sensor_keyword.strip()
    if not kw:
        return []
    term = f"%{kw}%"

    if col == "u2":
        sql = """
            SELECT p.doi, p.title, p.author, d.u2 AS uncertainty_text
            FROM datasets d
            JOIN papers p ON p.doi = d.doi
            WHERE d.u2 LIKE ?
            ORDER BY p.title
        """
        cur = conn.execute(sql, (term,))
    else:
        sql = f"""
            SELECT p.doi, p.title, p.author, fm.{col} AS uncertainty_text
            FROM fusion_methods fm
            JOIN papers p ON p.doi = fm.doi
            WHERE fm.{col} LIKE ?
            ORDER BY p.title
        """
        cur = conn.execute(sql, (term,))

    return [
        {
            "doi": r[0],
            "title": r[1],
            "author": r[2],
            "uncertainty_text": r[3],
        }
        for r in cur.fetchall()
    ]


def query_popular_dataset(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute(
        """
        SELECT
            ds.data_name,
            COUNT(DISTINCT fm.id) AS method_count,
            MIN(ds.doi) AS doi
        FROM datasets ds
        INNER JOIN fusion_methods fm ON fm.doi = ds.doi
        WHERE ds.data_name IS NOT NULL AND TRIM(ds.data_name) != ''
        GROUP BY ds.data_name
        ORDER BY method_count DESC
        LIMIT 10
        """
    )
    return [
        {"data_name": r[0], "method_count": r[1], "doi": r[2]}
        for r in cur.fetchall()
    ]
