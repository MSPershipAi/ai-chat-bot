import os
from typing import List, Optional, Tuple
from pathlib import Path
import logging
import re
import numpy as np  # type: ignore
import hashlib
import json
from datetime import datetime

import pdfplumber  # type: ignore
from langchain_ollama import OllamaEmbeddings  # type: ignore
from langchain_community.vectorstores import FAISS  # type: ignore
from langchain_core.documents import Document  # type: ignore
from langchain_text_splitters import RecursiveCharacterTextSplitter  # type: ignore

from io import BytesIO
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_text(text: str) -> str:
    """Normalize whitespace and fix hyphenation artefacts from PDF extraction."""
    if not text:
        return ""
    # Fix hyphenated line-breaks (e.g. "infor-\nmation" → "information")
    text = re.sub(r"-\n(\S)", r"\1", text)
    # Collapse multiple spaces / tabs into a single space
    text = re.sub(r"[ \t]+", " ", text)
    # Keep double newlines (paragraph breaks) but collapse 3+ into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_section_title(page, page_index: int) -> str:
    """
    Heuristically extract a section heading from a page.
    Looks for the largest-font text block in the top 30% of the page.
    Falls back to 'Page N' if nothing is found.
    """
    try:
        words = page.extract_words(extra_attrs=["size", "fontname"])
        if not words:
            return f"Page {page_index + 1}"

        page_height = page.height
        top_zone = page_height * 0.30  # top 30% of the page

        # Gather words in the top zone, find the largest font size
        top_words = [w for w in words if float(w.get("top", page_height)) < top_zone]
        if not top_words:
            return f"Page {page_index + 1}"

        max_size = max(float(w.get("size", 0)) for w in top_words)
        heading_words = [
            w["text"] for w in top_words
            if abs(float(w.get("size", 0)) - max_size) < 1.0
        ]
        title = " ".join(heading_words).strip()
        return title if len(title) > 2 else f"Page {page_index + 1}"
    except Exception:
        return f"Page {page_index + 1}"


def _extract_tables_as_markdown(page) -> str:
    """Extract tables from a pdfplumber page and format as Markdown."""
    tables_md = []
    try:
        tables = page.extract_tables()
        for table in tables:
            if not table:
                continue
            rows_md = []
            for i, row in enumerate(table):
                clean_row = [str(cell).strip() if cell else "" for cell in row]
                rows_md.append("| " + " | ".join(clean_row) + " |")
                if i == 0:
                    rows_md.append("|" + "|".join(["---"] * len(clean_row)) + "|")
            tables_md.append("\n".join(rows_md))
    except Exception as e:
        logger.warning(f"Table extraction failed: {e}")
    return "\n\n".join(tables_md)


def _extract_page_text(page, page_index: int, crop_margin: float = 0.08) -> str:
    """
    Extract clean body text from a single pdfplumber page.
    Strips header (top `crop_margin` %) and footer (bottom `crop_margin` %).
    """
    try:
        h = page.height
        w = page.width
        top_margin = h * crop_margin
        bottom_margin = h * (1.0 - crop_margin)

        # Crop the page to body area only
        body = page.within_bbox((0, top_margin, w, bottom_margin))
        text = body.extract_text(layout=True) or ""
        return _clean_text(text)
    except Exception as e:
        logger.warning(f"Page {page_index + 1} text extraction failed: {e}")
        return ""


class DocumentProcessor:
    def __init__(self, config: Optional[dict] = None):
        print("\n ..........Initializing Document Processor........ \n")
        """
        Initialize the document processor with FAISS configuration.

        Args:
            config: Dictionary containing configuration parameters.
                   Defaults will be used for any missing keys.
        """
        # Default configuration — smaller chunks preserve semantic meaning better
        default_config = {
            "embedding_model": "embeddinggemma",
            "pdf_dir": "uploaded_docs",
            "faiss_index_path": "FAISS_Index",
            "processed_files_json": "FAISS_Index/processed_files.json",
            "chunk_size": 600,       # ↓ from 1000 — more precise retrieval
            "chunk_overlap": 100,    # ↓ from 200 — less redundant context
        }
        self.vector_store_path = Path(default_config["faiss_index_path"])
        self.PDF_file_path = Path(default_config["pdf_dir"])
        self.pdf_file_processed_json = Path(default_config["processed_files_json"])
        self.processed_files = []
        self.config = {**default_config, **(config or {})}

        temp_dir = Path("FAISS_Index")
        self.processed_log_path = Path(temp_dir / "processed_files.json")

        # Embeddings are initialized lazily on first use to avoid a network
        # connection attempt to Ollama at import/startup time (which would crash
        # the server if Ollama isn't running yet).
        self._embeddings = None
        self._setup_directories()
        self.vector_db = None
        self.pdf_file_processed_hash = None
        self.processed_files_path = Path(self.vector_store_path / "processed_files.json")
        self.processed_files = self._load_processed_files()

    @property
    def embeddings(self) -> OllamaEmbeddings:
        """Return (and lazily create) the OllamaEmbeddings instance."""
        if self._embeddings is None:
            ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self._embeddings = OllamaEmbeddings(
                model=self.config["embedding_model"],
                base_url=ollama_base_url,
            )
            logger.info(f"OllamaEmbeddings initialized (base_url={ollama_base_url})")
        return self._embeddings

    # -----------------------------------------------------------------------
    # File tracking helpers
    # -----------------------------------------------------------------------

    def _load_processed_files(self) -> dict:
        """Track processed files with their hashes."""
        print("\n Loading processed files...\n")
        try:
            if not self.processed_files_path.exists():
                with open(self.processed_log_path, "w") as f:
                    json.dump([], f)
                print("\n Processed files file created.\n")
                return []

            print("\n Processed files file exists.\n")
            with open(self.processed_log_path, "r", encoding="utf-8") as j_file:
                re_json = json.load(j_file)
                print("\n Processed files:", re_json, "\n")
                return re_json
        except Exception as e:
            logger.error(f"\n Error loading processed files: {e} \n")
            return []

    def _save_processed_files(self, file_name):
        """Save processing records."""
        with open(self.processed_files_path, "w") as f:
            json.dump(file_name, f, indent=2)

    def _get_file_hash(self, file_path: Path) -> str:
        """Generate unique MD5 hash for file contents."""
        file_path = os.path.join(file_path)
        print("Hashlib Path: ", file_path)
        with open(file_path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()

    def is_file_processed(self, file_path: Path) -> bool:
        self.processed_files = self._load_processed_files()
        print("Check if file was already processed")
        print("File Path: ", file_path)
        file_path = os.path.join(file_path)
        file_hash = self._get_file_hash(file_path)
        print("Hash:", file_hash)
        print("Processed Files: ", self.processed_files)

        if self.processed_files is None:
            self.processed_files = []
            print("Processed files None!!!")
        else:
            hashes_available = [item["hash"] for item in self.processed_files]
            print(hashes_available)
            if file_hash in hashes_available:
                print(f"File {file_path} has already been processed.")
                self.pdf_file_processed_hash = file_hash
            else:
                self.pdf_file_processed_hash = None

        print("#1 : Hash file len: ", self.pdf_file_processed_hash)
        return self.pdf_file_processed_hash

    # -----------------------------------------------------------------------
    # PDF Extraction — pdfplumber based
    # -----------------------------------------------------------------------

    def load_and_split_documents(self, file_path: Path) -> List[Document]:
        """
        Load and split a PDF using pdfplumber.

        Improvements over the old PyPDFLoader approach:
        - Strips headers and footers via bounding-box cropping
        - Preserves paragraph structure (double newlines)
        - Extracts and attaches tables as Markdown text blocks
        - Adds section-title prefix to every chunk for better LLM context
        - Smaller chunks (600 chars / 100 overlap) improve retrieval precision

        Args:
            file_path: Path to the PDF file.
        Returns:
            List of LangChain Document chunks.
        """
        try:
            logger.info(f"Loading PDF with pdfplumber: {file_path}")
            doc_title = Path(file_path).stem
            raw_documents: List[Document] = []

            with pdfplumber.open(str(file_path)) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    page_num = page_index + 1
                    page_label = str(page_num)

                    # 1. Extract body text (header/footer stripped)
                    body_text = _extract_page_text(page, page_index, crop_margin=0.08)

                    # 2. Extract tables as Markdown and append to body text
                    table_text = _extract_tables_as_markdown(page)
                    if table_text:
                        body_text = body_text + "\n\n[TABLE]\n" + table_text

                    if not body_text.strip():
                        logger.debug(f"Page {page_num} had no extractable text, skipping.")
                        continue

                    # 3. Derive a section heading for context prefix
                    section_title = _extract_section_title(page, page_index)

                    # 4. Prefix body with doc + section context so every chunk is self-contained
                    prefixed_text = (
                        f"[Document: {doc_title}] [Section: {section_title}]\n\n"
                        + body_text
                    )

                    raw_documents.append(
                        Document(
                            page_content=prefixed_text,
                            metadata={
                                "source": str(file_path),
                                "page_label": page_label,
                                "page_number": page_num,
                                "section_title": section_title,
                                "doc_title": doc_title,
                            },
                        )
                    )

            logger.info(f"Extracted {len(raw_documents)} pages from {file_path}")

            # 5. Semantic chunking — prioritize paragraph breaks
            text_splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.config["chunk_size"],
                chunk_overlap=self.config["chunk_overlap"],
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            chunks = text_splitter.split_documents(raw_documents)
            logger.info(f"Split into {len(chunks)} chunks (size={self.config['chunk_size']}, overlap={self.config['chunk_overlap']})")
            return chunks

        except Exception as e:
            logger.error(f"Error loading/splitting documents: {str(e)}")
            return []

    # -----------------------------------------------------------------------
    # Vector store management
    # -----------------------------------------------------------------------

    def create_vector_store(self, chunks: List[Document]) -> bool:
        """
        Create or update the FAISS vector store by appending new documents.

        Args:
            chunks: List of document chunks to store or append.
        Returns:
            True if successful, False otherwise.
        """
        print("#2 : Hash file len: ", self.pdf_file_processed_hash)
        try:
            index_file = self.faiss_index_path / "faiss_index"

            if self.pdf_file_processed_hash is None:
                if index_file.exists():
                    # Load existing index and append new documents
                    logger.info("Loading existing FAISS index and appending documents...")
                    self.vector_db = FAISS.load_local(
                        str(index_file), self.embeddings, allow_dangerous_deserialization=True
                    )
                    self.vector_db.add_documents(chunks)
                else:
                    # Create fresh index
                    logger.info("Creating new FAISS index from scratch...")
                    self.vector_db = FAISS.from_documents(chunks, self.embeddings)

            elif self.pdf_file_processed_hash is not None:
                print("PDF is already in database.")
                logger.info("PDF already exists in database; loading index without changes.")
                if index_file.exists():
                    self.vector_db = FAISS.load_local(
                        str(index_file), self.embeddings, allow_dangerous_deserialization=True
                    )
                else:
                    logger.warning("Hash found but no FAISS index on disk — rebuilding.")
                    self.vector_db = FAISS.from_documents(chunks, self.embeddings)

            # Persist
            self.vector_db.save_local(str(index_file))
            logger.info(f"FAISS index saved to {index_file}")

            if len(self.vector_db.index_to_docstore_id) >= len(chunks):
                return True

            logger.warning(
                f"Item count mismatch: expected at least {len(chunks)}, "
                f"got {len(self.vector_db.index_to_docstore_id)}"
            )
            return False

        except Exception as e:
            logger.error(f"Error creating/updating FAISS index: {str(e)}")
            return False

    def process_pdf_from_buffer(self, buffer: BytesIO, filename: str, summary: str, keep_file: bool = False) -> bool:
        """Process an in-memory PDF buffer, embed it and add to FAISS."""
        document_summary = summary.strip()
        temp_dir = Path("temp_uploaded_docs")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / filename

        with open(temp_path, "wb") as f:
            f.write(buffer.getbuffer())

        # Extract and chunk
        documents = self.load_and_split_documents(temp_path)
        if not documents:
            raise ValueError("No documents extracted from PDF.")

        print("vector store creation...")
        vector_added_to_DB = self.create_vector_store(documents)

        if vector_added_to_DB:
            print("PDF processing complete.")
            hash_for_this_file = self._get_file_hash(temp_path)

            processed_file_info = {
                "filename": filename,
                "path": str(temp_path.resolve()),
                "processed": True,
                "discription": document_summary,
                "hash": hash_for_this_file,
                "date-time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "chunk_count": len(documents),
            }

            processed_log_path = Path(self.vector_store_path, "processed_files.json")
            if processed_log_path.exists():
                with open(processed_log_path, "r") as f:
                    processed_log = json.load(f)
            else:
                processed_log = []

            # Skip appending if this file hash is already recorded (prevents duplicate log entries)
            existing_hashes = {item["hash"] for item in processed_log}
            if hash_for_this_file not in existing_hashes:
                processed_log.append(processed_file_info)
                with open(processed_log_path, "w") as f:
                    json.dump(processed_log, f, indent=2)

            # Clean up temp file only when not bootstrapping from an existing file
            if not keep_file:
                temp_path.unlink()
            return True
        else:
            return False

    def _setup_directories(self) -> None:
        """Ensure required directories exist."""
        self.pdf_dir = Path(self.config["pdf_dir"])
        self.faiss_index_path = Path(self.config["faiss_index_path"])
        self.pdf_dir.mkdir(parents=True, exist_ok=True)
        self.faiss_index_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"PDF directory: {self.pdf_dir}")
        logger.info(f"FAISS index path: {self.faiss_index_path}")

    def process_pdf(self, file_name: str) -> bool:
        """
        Process a PDF file from the configured pdf_dir.

        Args:
            file_name: Name of the PDF file in the pdf_dir.
        Returns:
            True if successful, False otherwise.
        """
        pdf_path = self.pdf_dir / file_name

        if not pdf_path.exists():
            logger.error(f"PDF file not found: {pdf_path}")
            return False

        chunks = self.load_and_split_documents(pdf_path)
        if not chunks:
            return False

        if self.create_vector_store(chunks):
            file_hash = self._get_file_hash(pdf_path)
            self.processed_files[file_hash] = {
                "file_name": file_name,
                "processed_at": datetime.now().isoformat(),
                "chunk_count": len(chunks),
            }
            self._save_processed_files(file_name)
            return True

        return False

    # -----------------------------------------------------------------------
    # Querying — fixed L2 distance filter
    # -----------------------------------------------------------------------

    def query_documents(
        self,
        question: str,
        k: int = 6,
        max_distance: float = 1.5,
    ) -> List[Document]:
        """
        Query the FAISS index for relevant documents.

        IMPORTANT — FAISS `similarity_search_with_score` returns **L2 distance**.
        Lower score = more similar (opposite of cosine similarity).
        The old code used `score > min_score` which was WRONG — it kept distant
        (irrelevant) chunks and discarded close (relevant) ones.
        Fixed: keep chunks where `score < max_distance`.

        Args:
            question:     The query string.
            k:            Number of candidate results to retrieve (default 6).
            max_distance: Maximum L2 distance to accept (default 1.5).
                          Lower → stricter; tune by checking printed scores.
        Returns:
            List of relevant Document objects, sorted by relevance.
        """
        try:
            if not self.vector_db:
                index_file = self.faiss_index_path / "faiss_index"
                self.vector_db = FAISS.load_local(
                    str(index_file),
                    self.embeddings,
                    allow_dangerous_deserialization=True,
                )

            # Retrieve top-k candidates with their L2 distances
            results_with_scores = self.vector_db.similarity_search_with_score(question, k=k)

            # Log all scores so you can tune max_distance
            logger.info("--- Retrieval scores (L2 distance, lower = more similar) ---")
            for doc, score in results_with_scores:
                src = doc.metadata.get("source", "?").split("\\")[-1].split("/")[-1]
                page = doc.metadata.get("page_label", "?")
                logger.info(f"  score={score:.4f}  [{src} p.{page}]  {doc.page_content[:80]!r}...")

            # FIX: keep documents with LOW L2 distance (close = relevant)
            filtered = [doc for doc, score in results_with_scores if score < max_distance]

            if not filtered:
                logger.warning(
                    f"No documents passed the distance threshold (max_distance={max_distance}). "
                    f"Min score seen: {min(s for _, s in results_with_scores):.4f}"
                )
                # Fallback: return top-3 regardless of threshold
                logger.info("Returning top-3 results as fallback (no threshold applied).")
                return [doc for doc, _ in results_with_scores[:3]]

            logger.info(f"Found {len(filtered)} relevant documents (max_distance={max_distance})")
            return filtered

        except Exception as e:
            logger.error(f"Error querying documents: {str(e)}")
            return []


def main():
    processor = DocumentProcessor()
    results = processor.query_documents("Pership dresscode for men that New recruits?")
    for i, doc in enumerate(results, 1):
        logger.info(f"\nResult {i}:\n{doc.page_content[:500]}...")


if __name__ == "__main__":
    main()