import re
import os
import logging
import json
from groq import Groq  # type: ignore
from Vector_DB_Create import DocumentProcessor

logger = logging.getLogger(__name__)


class RAGAgent:
    def __init__(self):
        self.LLM_response_model = "llama-3.3-70b-versatile"
        self.HyDE_model = "llama-3.1-8b-instant"   # Fast cheap model for HyDE expansion

        self.RAG_Agent_prompt = """\
You are Equilibrium.ai, the personal AI assistant for Pership Group. Follow these rules:
1. Answer questions using ONLY the provided documents. Start with the most important information.
2. ALWAYS respond in this EXACT JSON format:
```json
{"Answer": "Your concise answer with bullet points here referring to the provided documents.",
 "summary": "A summary of the provided review content. Make it as long as you need to answer the question."
}```
3. Use a polite and precise tone. Present the answer in human-readable formatting with bullet points.
4. Cite sources in the answer (e.g., "Page 5 of HR Policy").
Requirements:
  Do NOT include any text outside the JSON block.
  Do NOT give conversational follow-ups (e.g. "Do you want to summarize?").
  If unsure, say: {"Answer": "I couldn't find this in the documents."}
Available Documents:"""

        self.vector_db_query = DocumentProcessor()

        from dotenv import load_dotenv
        load_dotenv()
        GROQ_API_KEY = os.getenv("GROQ_API_KEY")
        if not GROQ_API_KEY:
            try:
                config_data = json.load(open("config.json"))
                GROQ_API_KEY = config_data["GROQ_API_KEY"]
            except Exception:
                raise ValueError("GROQ_API_KEY must be defined in .env or config.json")
        os.environ["GROQ_API_KEY"] = GROQ_API_KEY
        self.client = Groq(api_key=GROQ_API_KEY)

    # -----------------------------------------------------------------------
    # HyDE — Hypothetical Document Embedding
    # -----------------------------------------------------------------------

    def _generate_hypothetical_answer(self, user_input: str) -> str:
        """
        Generate a short hypothetical document passage that would answer the question.

        This is the HyDE (Hypothetical Document Embeddings) technique:
        instead of embedding the raw user question (which often uses different
        vocabulary than the source PDF), we ask the LLM to write a brief
        "ideal answer snippet" and then embed THAT for retrieval.

        This significantly closes the vocabulary gap between questions and
        embedded document text, improving retrieval recall.

        Args:
            user_input: The user's question.
        Returns:
            A short hypothetical passage (2-4 sentences) relevant to the question.
        """
        try:
            hyde_prompt = (
                "Write a short 2-4 sentence passage that directly answers the following question. "
                "Write as if it is an extract from an official company policy or HR document. "
                "Do NOT include any preamble — output only the passage text.\n\n"
                f"Question: {user_input}"
            )
            response = self.client.chat.completions.create(
                model=self.HyDE_model,
                messages=[{"role": "user", "content": hyde_prompt}],
                temperature=0.3,
                max_tokens=200,
            )
            hypothetical = response.choices[0].message.content.strip()
            logger.info(f"🔍 HyDE hypothetical passage: {hypothetical[:120]}...")
            return hypothetical
        except Exception as e:
            logger.warning(f"HyDE generation failed, falling back to raw query: {e}")
            return user_input  # Graceful fallback to original question

    # -----------------------------------------------------------------------
    # Main RAG response
    # -----------------------------------------------------------------------

    def RAG_Agent_response(self, user_input: str, avalible_docs: dict, previous_messages: str = ""):
        """
        Full RAG pipeline:
          1. Generate a hypothetical answer (HyDE) to improve retrieval
          2. Query FAISS with the hypothetical passage
          3. Format retrieved chunks as context
          4. Call LLM for a final grounded answer
        """
        # Clone the base prompt and append available docs list
        prompt_with_docs = self.RAG_Agent_prompt + str(avalible_docs)
        logger.info("🗄️ RAG Agent is processing...")

        # ── Step 1: HyDE — generate a hypothetical passage for better retrieval ──
        logger.info("🔮 Running HyDE query expansion...")
        hypothetical_query = self._generate_hypothetical_answer(user_input)

        # ── Step 2: Retrieve relevant chunks ──
        try:
            # Query with the hypothetical passage for improved semantic matching
            raw_reviews = self.vector_db_query.query_documents(hypothetical_query)

            # Cap at top 5 chunks for LLM context window
            reviews = raw_reviews[:5]

            # Build source citation list (deduplicated)
            review_list = []
            for review in reviews:
                try:
                    citation = (
                        f"Page {review.metadata['page_label']} (Page Label) of "
                        f"{review.metadata['source'].split('/')[-1].split(chr(92))[-1]}"
                    )
                    if citation not in review_list:
                        review_list.append(citation)
                except Exception as e:
                    review_list.append(review.metadata.get("source", "Unknown source"))
                    print(f"Error processing review metadata: {e}")

            print("Raw Reviews:\n", review_list)

            if review_list:
                review_sources = "\n".join([f"- 📄 {item}" for item in review_list])
            else:
                review_sources = "\n".join([
                    f"- 📄 Page {r.metadata['page_label']} (Page Label) of "
                    f"'{r.metadata['source'].split(chr(92))[-1]}'"
                    for r in reviews
                ])

            # Build context string with page-level attribution
            review_by_chunk = "\n\n".join([
                f"[Page {r.metadata['page_label']} of '{r.metadata['source'].split(chr(92))[-1]}']\n"
                f"{r.page_content}"
                for r in reviews
            ])
            print("Review by chunk:\n", review_by_chunk[:500])

        except Exception as e:
            logger.error(f"Document retrieval error: {e}")
            review_by_chunk = ""
            review_sources = ""

        # ── Step 3: Build final prompt ──
        prompt_part = (
            f"USER_PROMPT: {user_input}\n"
            f"PREVIOUS_MESSAGES: {previous_messages}\n"
            f"AVAILABLE_DOCUMENTS:\n{review_by_chunk}"
        )

        # ── Step 4: LLM answer generation ──
        RAG_response = self.client.chat.completions.create(
            model=self.LLM_response_model,
            messages=[
                {"role": "system", "content": prompt_with_docs},
                {"role": "user", "content": prompt_part},
            ],
            temperature=0,
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        RAG_response_content = RAG_response.choices[0].message.content
        print(f"RAG Response: {RAG_response_content}")
        print(f"Review Sources: {review_sources}")

        return json.loads(RAG_response_content), review_sources

    # -----------------------------------------------------------------------
    # Legacy query method (kept for API compatibility)
    # -----------------------------------------------------------------------

    def query(self, user_input: str, previous_messages: str = "") -> dict:
        """
        Simplified query method (no HyDE). Kept for backward compatibility.

        Args:
            user_input:        User's question.
            previous_messages: Chat history (optional).
        Returns:
            dict with keys "answer" and "sources".
        """
        try:
            raw_reviews = self.vector_db_query.query_documents(user_input)
            reviews = raw_reviews[:3]

            review_sources = "\n".join(
                f"- 📄 Page {r.metadata['page_label']} of '{r.metadata['source'].split('/')[-1]}'"
                for r in reviews
            )

            context = "\n".join(
                f"Page {r.metadata['page_label']} of '{r.metadata['source'].split('/')[-1]}': {r.page_content}"
                for r in reviews
            )

            prompt = (
                f"[USER QUESTION]\n{user_input}\n\n"
                f"[DOCUMENT CONTEXT]\n{context}\n\n"
                "Answer concisely and cite sources."
            )

            response = self.client.chat.completions.create(
                model=self.LLM_response_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=400,
            )

            return {
                "answer": response.choices[0].message.content,
                "sources": review_sources,
            }

        except Exception as e:
            return {
                "answer": f"⚠️ Error: {str(e)}",
                "sources": "",
            }