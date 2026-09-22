from __future__ import annotations

from collections.abc import Sequence
from datetime import date
import sqlite3
from typing import TYPE_CHECKING, Literal

import numpy as np

from financial_research_agent.rag.models import ReportChunk, RetrievalHit

if TYPE_CHECKING:
    from financial_research_agent.config import Settings

COLLECTION_NAME = "research_reports_v2"


def _quoted(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


class MilvusReportStore:
    def __init__(self, settings: Settings, collection_name: str = COLLECTION_NAME) -> None:
        self.settings = settings
        self.collection_name = collection_name
        self._client = None

    def _connect(self):
        from pymilvus import MilvusClient

        if self._client is None:
            uri = f"http://{self.settings.milvus_host}:{self.settings.milvus_port}"
            self._client = MilvusClient(uri=uri)
        return self._client

    def _new_collection(self, dimension: int) -> None:
        from pymilvus import DataType, MilvusClient

        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field(
            field_name="chunk_id", datatype=DataType.VARCHAR, is_primary=True, max_length=64
        )
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field(field_name="document_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="stock_code", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="stock_name", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="institution", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="report_title", datatype=DataType.VARCHAR, max_length=512)
        schema.add_field(field_name="report_date", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="date_unknown", datatype=DataType.BOOL)
        schema.add_field(field_name="page_number", datatype=DataType.INT64)
        schema.add_field(field_name="source_path", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=8192)
        schema.add_field(field_name="parent_chunk_id", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="parent_text", datatype=DataType.VARCHAR, max_length=12000)
        schema.add_field(field_name="section_title", datatype=DataType.VARCHAR, max_length=256)
        schema.add_field(field_name="chunk_ordinal", datatype=DataType.INT64)
        schema.add_field(field_name="content_hash", datatype=DataType.VARCHAR, max_length=64)
        schema.add_field(field_name="document_version", datatype=DataType.VARCHAR, max_length=32)
        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding", index_type="AUTOINDEX", metric_type="IP", params={}
        )
        self.client.create_collection(
            collection_name=self.collection_name,
            schema=schema,
            index_params=index_params,
            description="Page-addressable Chinese research reports",
        )

    @staticmethod
    def _vector_dimension(description: dict) -> int:
        field = next(field for field in description["fields"] if field["name"] == "embedding")
        return int(field["params"]["dim"])

    def prepare(self, dimension: int, mode: Literal["rebuild", "skip"] = "skip") -> None:
        client = self._connect()
        exists = client.has_collection(self.collection_name)
        if exists and mode == "rebuild":
            client.drop_collection(self.collection_name)
            exists = False
        if exists:
            actual = self._vector_dimension(client.describe_collection(self.collection_name))
            if actual != dimension:
                raise ValueError(
                    f"collection dimension mismatch: expected {dimension}, found {actual}; "
                    "run with --mode rebuild to replace it explicitly"
                )
        else:
            self._new_collection(dimension)

    @property
    def client(self):
        if self._client is None:
            return self._connect()
        return self._client

    def count(self) -> int:
        self.client.flush(self.collection_name)
        stats = self.client.get_collection_stats(self.collection_name)
        return int(stats["row_count"])

    def insert(self, chunks: Sequence[ReportChunk], vectors: np.ndarray) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunk and vector counts differ")
        if not chunks:
            return 0
        rows = [
            {
                **chunk.model_dump(mode="json"),
                "report_date": chunk.report_date.isoformat() if chunk.report_date else "",
                "embedding": vector.tolist(),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        result = self.client.insert(self.collection_name, rows)
        self.client.flush(self.collection_name)
        return int(result["insert_count"])

    def replace(self, chunks: Sequence[ReportChunk], vectors: np.ndarray) -> int:
        if not chunks:
            return 0
        document_ids = sorted({item.document_id for item in chunks})
        expression = ",".join(f'"{_quoted(item)}"' for item in document_ids)
        self.client.delete(
            collection_name=self.collection_name,
            filter=f"document_id in [{expression}]",
        )
        self.client.flush(self.collection_name)
        return self.insert(chunks, vectors)

    def prune_documents(self, active_document_ids: set[str]) -> int:
        self.client.load_collection(self.collection_name)
        rows = self.client.query(
            collection_name=self.collection_name,
            filter='document_id != ""',
            output_fields=["document_id"],
            limit=16_384,
        )
        stale = sorted(
            {str(item["document_id"]) for item in rows} - active_document_ids
        )
        if not stale:
            return 0
        expression = ",".join(f'"{_quoted(item)}"' for item in stale)
        self.client.delete(
            collection_name=self.collection_name,
            filter=f"document_id in [{expression}]",
        )
        self.client.flush(self.collection_name)
        return len(stale)

    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        client = self.client
        client.load_collection(self.collection_name)
        output_fields = [
            "chunk_id",
            "document_id",
            "stock_code",
            "stock_name",
            "institution",
            "report_title",
            "report_date",
            "date_unknown",
            "page_number",
            "source_path",
            "text",
            "parent_chunk_id",
            "parent_text",
            "section_title",
            "chunk_ordinal",
            "content_hash",
            "document_version",
        ]
        clauses = [f'stock_code == "{_quoted(stock_code)}"']
        filters = filters or {}
        if filters.get("start_date"):
            clauses.append(f'report_date >= "{_quoted(str(filters["start_date"]))}"')
        if filters.get("end_date"):
            clauses.append(f'report_date <= "{_quoted(str(filters["end_date"]))}"')
        if filters.get("institution"):
            clauses.append(f'institution == "{_quoted(str(filters["institution"]))}"')
        if filters.get("document_ids"):
            document_ids = ",".join(
                f'"{_quoted(str(item))}"' for item in filters["document_ids"]
            )
            clauses.append(f"document_id in [{document_ids}]")
        results = client.search(
            collection_name=self.collection_name,
            data=[np.asarray(query_vector, dtype=np.float32).tolist()],
            anns_field="embedding",
            search_params={"metric_type": "IP", "params": {}},
            limit=top_k,
            filter=" and ".join(clauses),
            output_fields=output_fields,
        )
        hits: list[RetrievalHit] = []
        for hit in results[0]:
            row = {field: hit["entity"].get(field) for field in output_fields}
            raw_date = row.get("report_date")
            row["report_date"] = date.fromisoformat(raw_date) if raw_date else None
            score = float(hit["distance"])
            hits.append(
                RetrievalHit(
                    **row,
                    score=score,
                    dense_score=score,
                    retrieval_strategy="dense",
                )
            )
        return hits


class SqliteKeywordReportStore:
    """Small, persistent lexical index; Milvus remains the dense vector store."""

    def __init__(self, settings: Settings) -> None:
        self.path = settings.rag_keyword_index_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def prepare(self, mode: Literal["rebuild", "skip", "incremental"] = "skip") -> None:
        from pathlib import Path

        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            if mode == "rebuild":
                connection.execute("DROP TABLE IF EXISTS report_chunks_fts")
                connection.execute("DROP TABLE IF EXISTS report_chunks")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS report_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS report_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        stock_code UNINDEXED,
                        report_date UNINDEXED,
                        institution UNINDEXED,
                        section_title,
                        text,
                        parent_text,
                        tokenize='trigram'
                    )
                    """
                )
            except sqlite3.OperationalError:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS report_chunks_fts USING fts5(
                        chunk_id UNINDEXED,
                        document_id UNINDEXED,
                        stock_code UNINDEXED,
                        report_date UNINDEXED,
                        institution UNINDEXED,
                        section_title,
                        text,
                        parent_text,
                        tokenize='unicode61'
                    )
                    """
                )

    def count(self) -> int:
        self.prepare(mode="incremental")
        with self._connect() as connection:
            row = connection.execute("SELECT count(*) FROM report_chunks").fetchone()
        return int(row[0]) if row else 0

    def replace(self, chunks: Sequence[ReportChunk]) -> int:
        if not chunks:
            return 0
        self.prepare(mode="incremental")
        document_ids = sorted({item.document_id for item in chunks})
        placeholders = ",".join("?" for _ in document_ids)
        with self._connect() as connection:
            old_ids = [
                row[0]
                for row in connection.execute(
                    f"SELECT chunk_id FROM report_chunks_fts WHERE document_id IN ({placeholders})",
                    document_ids,
                )
            ]
            for chunk_id in old_ids:
                connection.execute("DELETE FROM report_chunks_fts WHERE chunk_id = ?", (chunk_id,))
                connection.execute("DELETE FROM report_chunks WHERE chunk_id = ?", (chunk_id,))
            for item in chunks:
                payload = item.model_dump_json()
                connection.execute(
                    "INSERT OR REPLACE INTO report_chunks(chunk_id, payload) VALUES (?, ?)",
                    (item.chunk_id, payload),
                )
                connection.execute(
                    """
                    INSERT INTO report_chunks_fts(
                        chunk_id, document_id, stock_code, report_date, institution,
                        section_title, text, parent_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.chunk_id,
                        item.document_id,
                        item.stock_code,
                        item.report_date.isoformat() if item.report_date else "",
                        item.institution,
                        item.section_title,
                        item.text,
                        item.parent_text,
                    ),
                )
        return len(chunks)

    def prune_documents(self, active_document_ids: set[str]) -> int:
        self.prepare(mode="incremental")
        with self._connect() as connection:
            known = {
                str(row[0])
                for row in connection.execute(
                    "SELECT DISTINCT document_id FROM report_chunks_fts"
                )
            }
            stale = sorted(known - active_document_ids)
            for document_id in stale:
                chunk_ids = [
                    row[0]
                    for row in connection.execute(
                        "SELECT chunk_id FROM report_chunks_fts WHERE document_id = ?",
                        (document_id,),
                    )
                ]
                connection.execute(
                    "DELETE FROM report_chunks_fts WHERE document_id = ?", (document_id,)
                )
                for chunk_id in chunk_ids:
                    connection.execute(
                        "DELETE FROM report_chunks WHERE chunk_id = ?", (chunk_id,)
                    )
        return len(stale)

    @staticmethod
    def _match_expression(query: str) -> str:
        import re

        normalized = re.sub(r"[^0-9A-Za-z\u3400-\u9fff]+", " ", query).strip()
        if len(normalized.replace(" ", "")) < 3:
            return '"' + normalized.replace('"', '""') + '"'
        parts = [item for item in normalized.split() if len(item) >= 3]
        parts = parts or [normalized]
        return " OR ".join('"' + item.replace('"', '""') + '"' for item in parts)

    def search(
        self,
        query: str,
        stock_code: str,
        top_k: int,
        *,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        import json

        filters = filters or {}
        clauses = ["report_chunks_fts MATCH ?", "stock_code = ?"]
        parameters: list[object] = [self._match_expression(query), stock_code]
        if filters.get("start_date"):
            clauses.append("report_date >= ?")
            parameters.append(str(filters["start_date"]))
        if filters.get("end_date"):
            clauses.append("report_date <= ?")
            parameters.append(str(filters["end_date"]))
        if filters.get("institution"):
            clauses.append("institution = ?")
            parameters.append(str(filters["institution"]))
        if filters.get("document_ids"):
            document_ids = list(filters["document_ids"])
            clauses.append(
                "document_id IN (" + ",".join("?" for _ in document_ids) + ")"
            )
            parameters.extend(document_ids)
        sql = (
            "SELECT chunk_id, bm25(report_chunks_fts) AS rank_score "
            "FROM report_chunks_fts WHERE "
            + " AND ".join(clauses)
            + " ORDER BY rank_score LIMIT ?"
        )
        parameters.append(top_k)
        with self._connect() as connection:
            try:
                rows = list(connection.execute(sql, parameters))
            except sqlite3.OperationalError:
                rows = []
            if not rows:
                return self._fallback_search(
                    connection,
                    query=query,
                    stock_code=stock_code,
                    top_k=top_k,
                    filters=filters,
                )
            hits: list[RetrievalHit] = []
            for row in rows:
                payload_row = connection.execute(
                    "SELECT payload FROM report_chunks WHERE chunk_id = ?", (row["chunk_id"],)
                ).fetchone()
                if payload_row is None:
                    continue
                payload = json.loads(payload_row["payload"])
                keyword_score = 1.0 / (1.0 + abs(float(row["rank_score"])))
                hits.append(
                    RetrievalHit(
                        **payload,
                        score=keyword_score,
                        keyword_score=keyword_score,
                        retrieval_strategy="keyword",
                    )
                )
        return hits

    @staticmethod
    def _fallback_search(
        connection: sqlite3.Connection,
        *,
        query: str,
        stock_code: str,
        top_k: int,
        filters: dict,
    ) -> list[RetrievalHit]:
        import json
        import re

        terms = [
            item.lower()
            for item in re.findall(r"[0-9A-Za-z]+|[\u3400-\u9fff]{2,}", query)
        ]
        allowed_documents = set(filters.get("document_ids") or [])
        scored: list[tuple[float, ReportChunk]] = []
        for row in connection.execute("SELECT payload FROM report_chunks"):
            chunk = ReportChunk.model_validate(json.loads(row["payload"]))
            if chunk.stock_code != stock_code:
                continue
            if filters.get("institution") and chunk.institution != filters["institution"]:
                continue
            if allowed_documents and chunk.document_id not in allowed_documents:
                continue
            if filters.get("start_date") and (
                not chunk.report_date or chunk.report_date < filters["start_date"]
            ):
                continue
            if filters.get("end_date") and (
                not chunk.report_date or chunk.report_date > filters["end_date"]
            ):
                continue
            haystack = f"{chunk.section_title}\n{chunk.text}\n{chunk.parent_text}".lower()
            matched = sum(haystack.count(term) for term in terms)
            if matched:
                scored.append((float(matched), chunk))
        scored.sort(key=lambda item: (-item[0], item[1].chunk_id))
        return [
            RetrievalHit(
                **chunk.model_dump(mode="python"),
                score=score,
                keyword_score=score,
                retrieval_strategy="keyword",
            )
            for score, chunk in scored[:top_k]
        ]


class HybridReportStore:
    def __init__(self, settings: Settings) -> None:
        self.dense = MilvusReportStore(settings)
        self.keyword = SqliteKeywordReportStore(settings)

    def prepare(self, dimension: int, mode: str = "skip") -> None:
        self.dense.prepare(dimension, mode="rebuild" if mode == "rebuild" else "skip")
        self.keyword.prepare(mode=mode)

    def replace(self, chunks: Sequence[ReportChunk], vectors: np.ndarray) -> int:
        dense_count = self.dense.replace(chunks, vectors)
        keyword_count = self.keyword.replace(chunks)
        if dense_count != keyword_count:
            raise RuntimeError("RAG_INDEX_COUNT_MISMATCH")
        return dense_count

    def assert_consistent(self) -> tuple[int, int]:
        dense_count = self.dense.count()
        keyword_count = self.keyword.count()
        if dense_count != keyword_count:
            raise RuntimeError(
                f"RAG_INDEX_TOTAL_COUNT_MISMATCH:dense={dense_count}:keyword={keyword_count}"
            )
        return dense_count, keyword_count

    def prune_documents(self, active_document_ids: set[str]) -> int:
        dense_count = self.dense.prune_documents(active_document_ids)
        keyword_count = self.keyword.prune_documents(active_document_ids)
        if dense_count != keyword_count:
            raise RuntimeError("RAG_PRUNE_COUNT_MISMATCH")
        return dense_count

    def search(
        self,
        query_vector: np.ndarray,
        stock_code: str,
        top_k: int,
        *,
        query_text: str | None = None,
        filters: dict | None = None,
    ) -> list[RetrievalHit]:
        candidate_k = min(max(top_k * 3, top_k), 30)
        dense_hits = self.dense.search(
            query_vector,
            stock_code,
            candidate_k,
            query_text=query_text,
            filters=filters,
        )
        keyword_hits = (
            self.keyword.search(query_text, stock_code, candidate_k, filters=filters)
            if query_text
            else []
        )
        by_id: dict[str, RetrievalHit] = {}
        scores: dict[str, float] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            by_id[hit.chunk_id] = hit
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (60 + rank)
        for rank, hit in enumerate(keyword_hits, start=1):
            current = by_id.get(hit.chunk_id)
            if current is None:
                by_id[hit.chunk_id] = hit
            else:
                by_id[hit.chunk_id] = current.model_copy(
                    update={"keyword_score": hit.keyword_score}
                )
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + 1.0 / (60 + rank)
        ordered = sorted(scores, key=lambda item: (-scores[item], item))[:top_k]
        # Preserve the strongest semantic match as the first result. Lexical RRF
        # still reranks and fills the remaining positions without degrading the
        # precision-oriented first hit used by evidence-grounded reports.
        if dense_hits and ordered:
            dense_anchor = dense_hits[0].chunk_id
            ordered = [dense_anchor, *[item for item in ordered if item != dense_anchor]][
                :top_k
            ]
        return [
            by_id[item].model_copy(
                update={
                    "score": scores[item],
                    "retrieval_strategy": "hybrid",
                    "text": by_id[item].parent_text or by_id[item].text,
                }
            )
            for item in ordered
        ]
