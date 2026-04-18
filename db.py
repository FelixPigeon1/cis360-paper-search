"""SQLite database helpers for the CIS 360 Data Fusion Knowledge System."""

from __future__ import annotations

import io
import os
import sqlite3
from typing import Any

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


def import_excel(conn: sqlite3.Connection, file_bytes: bytes) -> dict[str, int]:
    bio = io.BytesIO(file_bytes)
    doi_df = pd.read_excel(bio, sheet_name="DOI")
    bio.seek(0)
    data_df = pd.read_excel(bio, sheet_name="Data")
    bio.seek(0)
    fusion_df = pd.read_excel(bio, sheet_name="Fusion Method")

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
