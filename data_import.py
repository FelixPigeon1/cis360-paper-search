import sqlite3
import pandas as pd
import streamlit as st

col_map = {
    # id
    'id': 'id',
    'paper_id': 'id',
    'record_id': 'id',
    'entry_id': 'id',

    # doi
    'doi': 'doi',
    'digital_object_identifier': 'doi',
    'document_identifier': 'doi',

    # title
    'title': 'title',
    'paper_title': 'title',
    'article_title': 'title',
    'document_title': 'title',
    'name': 'title',

    # author
    'author': 'author',
    'authors': 'author',
    'author_name': 'author',
    'author_names': 'author',
    'creator': 'author',
    'creators': 'author',
    'writer': 'author',

    # publication_title
    'publication_title': 'publication_title',
    'journal': 'publication_title',
    'journal_title': 'publication_title',
    'source': 'publication_title',
    'source_title': 'publication_title',
    'venue': 'publication_title',
    'conference': 'publication_title',
    'book_title': 'publication_title',
    'container_title': 'publication_title',

    # publication_date
    'publication_date': 'publication_date',
    'date': 'publication_date',
    'pub_date': 'publication_date',
    'published_date': 'publication_date',
    'year': 'publication_date',
    'publication_year': 'publication_date',
    'pub_year': 'publication_date',
    'issued': 'publication_date',

    # url
    'url': 'url',
    'link': 'url',
    'uri': 'url',
    'web_url': 'url',
    'html_url': 'url',
    'pdf_url': 'url',
    'full_text_url': 'url',

    # keywords
    'keywords': 'keywords',
    'keyword': 'keywords',
    'tags': 'keywords',
    'subject': 'keywords',
    'subjects': 'keywords',
    'terms': 'keywords',
    'index_terms': 'keywords',
    'mesh_terms': 'keywords',

    # abstract
    'abstract': 'abstract',
    'summary': 'abstract',
    'description': 'abstract',
    'abstract_text': 'abstract',
    'paper_abstract': 'abstract',

    # publisher
    'publisher': 'publisher',
    'publisher_name': 'publisher',
    'publishing_house': 'publisher',
    'organization': 'publisher',

    # field_of_study
    'field_of_study': 'field_of_study',
    'field': 'field_of_study',
    'discipline': 'field_of_study',
    'research_area': 'field_of_study',
    'subject_area': 'field_of_study',
    'category': 'field_of_study',

    # is_data_fusion
    'is_data_fusion': 'is_data_fusion',
    'data_fusion': 'is_data_fusion',
    'data_fusion_flag': 'is_data_fusion',
    'uses_data_fusion': 'is_data_fusion',

    # classification_reason
    'classification_reason': 'classification_reason',
    'reason': 'classification_reason',
    'classification_notes': 'classification_reason',
    'notes': 'classification_reason',
    'rationale': 'classification_reason',

    # contributor_id
    'contributor_id': 'contributor_id',
    'contributor': 'contributor_id',
    'submitted_by': 'contributor_id',
    'added_by': 'contributor_id',
    'uploader_id': 'contributor_id',
}

# All recognized source keywords (keys of col_map, lowercased and stripped)
_col_map_keys = set(k.lower().strip() for k in col_map)


def _sheet_name_matches(sheet_name: str) -> set[str]:
    """Return col_map keys found as substrings in a sheet name."""
    name = sheet_name.lower().strip()
    return {k for k in _col_map_keys if k in name}


def _header_matches(headers) -> set[str]:
    """Return col_map keys found in a list of column headers."""
    normalized = {str(h).lower().strip() for h in headers if pd.notna(h)}
    return _col_map_keys & normalized


def identify_sources(path: str) -> dict[str, dict]:
    """
    Identify which sheets (xlsx) or file (csv) contain which standard columns.

    Returns a dict keyed by sheet/file name. Each value is:
        {
            "matched_via": "sheet_name" | "headers",
            "raw_keys":    set of matched col_map keys,
            "std_columns": set of mapped standard column names,
        }
    Only entries with at least one match are included.
    """
    results = {}

    if path.endswith('.csv'):
        df_head = pd.read_csv(path, nrows=0)
        header_hits = _header_matches(df_head.columns)
        if header_hits:
            results[path] = {
                'matched_via': 'headers',
                'raw_keys': header_hits,
                'std_columns': {col_map[k] for k in header_hits},
            }
        return results

    # xlsx
    xl = pd.ExcelFile(path)
    for sheet in xl.sheet_names:
        name_hits = _sheet_name_matches(sheet)
        if name_hits:
            results[sheet] = {
                'matched_via': 'sheet_name',
                'raw_keys': name_hits,
                'std_columns': {col_map[k] for k in name_hits},
            }
            continue

        # fall back to checking headers
        df_head = xl.parse(sheet, nrows=0)
        header_hits = _header_matches(df_head.columns)
        if header_hits:
            results[sheet] = {
                'matched_via': 'headers',
                'raw_keys': header_hits,
                'std_columns': {col_map[k] for k in header_hits},
            }

    return results


DB_PATH = 'data_fusion.db'

_SCHEMA = """
CREATE TABLE IF NOT EXISTS contributors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_file TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT,
    title TEXT,
    author TEXT,
    publication_title TEXT,
    publication_date TEXT,
    url TEXT,
    keywords TEXT,
    abstract TEXT,
    publisher TEXT,
    field_of_study TEXT,
    is_data_fusion TEXT,
    classification_reason TEXT,
    contributor_id INTEGER,
    FOREIGN KEY (contributor_id) REFERENCES contributors(id)
);

CREATE TABLE IF NOT EXISTS methods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    method_key TEXT,
    doi TEXT,
    description TEXT,
    u1 TEXT,
    u3 TEXT,
    contributor_id INTEGER,
    FOREIGN KEY (contributor_id) REFERENCES contributors(id)
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT,
    data_name TEXT,
    dataset_url TEXT,
    method_key TEXT,
    data_type TEXT,
    collection_method TEXT,
    u2 TEXT,
    spatial_coverage TEXT,
    temporal_coverage TEXT,
    format TEXT,
    license TEXT,
    provenance TEXT,
    contributor_id INTEGER,
    FOREIGN KEY (contributor_id) REFERENCES contributors(id)
);
"""


def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Create data_fusion.db with all tables if they don't already exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn

