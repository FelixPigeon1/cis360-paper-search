import sqlite3
import streamlit as st
from data_import import DB_PATH, init_db

st.set_page_config(page_title="CIS 360 Paper Search", layout="wide")
st.title("Academic Paper Search")


@st.cache_resource
def get_conn():
    return init_db(DB_PATH)


def search_papers(conn: sqlite3.Connection, keywords: list[str]) -> list[dict]:
    if not keywords:
        return []

    clauses = []
    params = []
    searchable = ["title", "abstract", "keywords", "author", "publication_title", "field_of_study"]
    for kw in keywords:
        term = f"%{kw}%"
        col_conditions = " OR ".join(f"p.{col} LIKE ?" for col in searchable)
        clauses.append(f"({col_conditions})")
        params.extend([term] * len(searchable))

    where = " AND ".join(clauses)
    sql = f"""
        SELECT p.id, p.doi, p.title, p.author, p.publication_title,
               p.publication_date, p.url, p.keywords, p.abstract,
               p.publisher, p.field_of_study, p.is_data_fusion,
               p.classification_reason, c.name AS contributor
        FROM papers p
        LEFT JOIN contributors c ON p.contributor_id = c.id
        WHERE {where}
        ORDER BY p.title
    """
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


conn = get_conn()

query = st.text_input("Enter keywords (comma-separated)", placeholder="e.g. data fusion, uncertainty, remote sensing")

if query:
    keywords = [k.strip() for k in query.split(",") if k.strip()]
    results = search_papers(conn, keywords)

    st.markdown(f"**{len(results)} result{'s' if len(results) != 1 else ''} found** for: {', '.join(f'`{k}`' for k in keywords)}")

    if results:
        for paper in results:
            with st.expander(paper["title"] or "*(no title)*"):
                col1, col2 = st.columns(2)
                with col1:
                    if paper["author"]:
                        st.markdown(f"**Author(s):** {paper['author']}")
                    if paper["publication_title"]:
                        st.markdown(f"**Published in:** {paper['publication_title']}")
                    if paper["publication_date"]:
                        st.markdown(f"**Date:** {paper['publication_date']}")
                    if paper["field_of_study"]:
                        st.markdown(f"**Field:** {paper['field_of_study']}")
                    if paper["publisher"]:
                        st.markdown(f"**Publisher:** {paper['publisher']}")
                    if paper["contributor"]:
                        st.markdown(f"**Contributor:** {paper['contributor']}")
                with col2:
                    if paper["doi"]:
                        st.markdown(f"**DOI:** `{paper['doi']}`")
                    if paper["url"]:
                        st.markdown(f"**URL:** {paper['url']}")
                    if paper["keywords"]:
                        st.markdown(f"**Keywords:** {paper['keywords']}")
                    if paper["is_data_fusion"]:
                        st.markdown(f"**Data Fusion:** {paper['is_data_fusion']}")
                    if paper["classification_reason"]:
                        st.markdown(f"**Classification Reason:** {paper['classification_reason']}")
                if paper["abstract"]:
                    st.markdown("**Abstract:**")
                    st.write(paper["abstract"])
    else:
        st.info("No papers matched your search. Try different or fewer keywords.")
