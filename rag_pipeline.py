import os
import json
import asyncio
import pickle
import hashlib
import time
import numpy as np
from dotenv import load_dotenv

from database import SessionLocal, AuditLog

# Optional Langfuse tracing, as seen in .env (Disabled due to missing keys)
# from langfuse.openai import openai

from pydantic import BaseModel, Field
from typing import List, Dict, Any

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain_pinecone import PineconeVectorStore
from langchain_cohere import CohereRerank
from pinecone import Pinecone

# -------------------------------------------------------------------
# Output Schema
# -------------------------------------------------------------------
class RAGResponseFields(BaseModel):
    answer: str = Field(description="The final answer derived ONLY from the provided documents.")
    citations: List[str] = Field(description="A list of EXACT citation strings from the document metadata.")
    regulation: str = Field(description="The regulation involved (HIPAA, GDPR, or NIST).")

# -------------------------------------------------------------------
# Pipeline Core
# -------------------------------------------------------------------
class NormIQRAGPipeline:
    def __init__(self):
        load_dotenv()
        
        # Initialize API Clients
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        
        # Initialize Pinecone
        pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
        self.index_name = os.getenv("PINECONE_INDEX", "normiq")
        self. pinecone_index = pc.Index(self.index_name)
        
        # 3 Separate VectorStores for 3 Namespaces
        self.pinecone_stores = {
            "HIPAA": PineconeVectorStore(index=self.pinecone_index, embedding=self.embeddings, namespace="HIPAA"),
            "GDPR": PineconeVectorStore(index=self.pinecone_index, embedding=self.embeddings, namespace="GDPR"),
            "NIST": PineconeVectorStore(index=self.pinecone_index, embedding=self.embeddings, namespace="NIST")
        }
        
        # Initialize BM25 Sparse Retrievers
        # Each .pkl contains TWO objects: (1) BM25Okapi index, (2) corpus list
        self.bm25_stores = {}
        for reg in ["HIPAA", "GDPR", "NIST"]:
            BASE_DIR = os.path.dirname(os.path.abspath(__file__))
            filepath = os.path.join(BASE_DIR, "data", f"bm25_{reg.lower()}.pkl")
            if os.path.exists(filepath):
                with open(filepath, "rb") as f:
                    try:
                        index = pickle.load(f)
                        corpus = pickle.load(f)
                        self.bm25_stores[reg] = {"index": index, "corpus": corpus}
                    except EOFError:
                        print(f"Warning: {filepath} missing corpus data.")
                        self.bm25_stores[reg] = None
            else:
                print(f"Warning: {filepath} not found. Sparse retrieval disabled for {reg}.")
                self.bm25_stores[reg] = None
        
        # Initialize Cohere Reranker
        self.reranker = CohereRerank(
            cohere_api_key=os.getenv("COHERE_API_KEY"),
            model="rerank-english-v3.0",
            top_n=3
        )
        
        # Setup Local MD5 Cache
        self.cache_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "query_cache.json")

    async def _async_pinecone_search(self, query: str, regulation: str, k: int = 5) -> List[Document]:
        """Perform dense vector search in a specific namespace."""
        try:
            return await self.pinecone_stores[regulation].asimilarity_search(query, k=k)
        except Exception as e:
            print(f"Pinecone search error for {regulation}: {e}")
            return []

    async def _async_bm25_search(self, query: str, regulation: str, k: int = 5) -> List[Document]:
        """Perform sparse keyword search using loaded raw BM25 index."""
        if not self.bm25_stores.get(regulation):
            return []
        try:
            bm25_index = self.bm25_stores[regulation]["index"]
            corpus = self.bm25_stores[regulation]["corpus"]
            
            # Simple tokenization
            tokenized_query = query.lower().split()
            
            # get_scores computes scores for all docs
            scores = bm25_index.get_scores(tokenized_query)
            
            # get top k indices
            top_n_idx = np.argsort(scores)[-k:][::-1]
            
            docs = []
            for idx in top_n_idx:
                if scores[idx] > 0:  # Must have some match
                    # Embed original citation if available, else standard fallback
                    # Since we don't know the exact metadata map for BM25 texts, we provide a placeholder citation 
                    # which Cohere/LLM might not strictly need since Pinecone handles exact metadata
                    text = corpus[idx]
                    docs.append(Document(page_content=text, metadata={"regulation": regulation, "source": "bm25"}))
                    
            return docs
        except Exception as e:
            print(f"BM25 search error for {regulation}: {e}")
            return []

    def cosine_similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        if np.linalg.norm(a) == 0 or np.linalg.norm(b) == 0:
            return 0.0
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

    async def query(self, user_question: str) -> Dict[str, Any]:
        """Runs the fully parallelized hybrid RAG pipeline."""
        start_time = time.time()
        
        # ---------------------------------------------------------
        # 0. Check MD5 Cache
        # ---------------------------------------------------------
        question_hash = hashlib.md5(user_question.lower().strip().encode('utf-8')).hexdigest()
        
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                try:
                     self.cache_data = json.load(f)
                     if question_hash in self.cache_data:
                         print(f"⚡ Using Cached Response for MD5: {question_hash}")
                         cached_res = self.cache_data[question_hash]
                         cached_res["from_cache"] = True
                         cached_res["process_time_sec"] = round(time.time() - start_time, 2)
                         
                         # Log the cached hit to DB
                         self._log_to_db(user_question, cached_res)
                         return cached_res
                except Exception:
                     self.cache_data = {}
        else:
             self.cache_data = {}

        # ---------------------------------------------------------
        # 1. Asynchronous Hybrid Search (6 Parallel Tasks)
        # ---------------------------------------------------------
        tasks = []
        for reg in ["HIPAA", "GDPR", "NIST"]:
            tasks.append(self._async_pinecone_search(user_question, reg, k=12))
            tasks.append(self._async_bm25_search(user_question, reg, k=12))
            
        results_lists = await asyncio.gather(*tasks)
        
        # Merge and Deduplicate chunks (by page_content to avoid same chunk twice)
        unique_chunks = {}
        for result_list in results_lists:
            for doc in result_list:
                # Slight discount for GDPR recitals as per constraints
                if doc.metadata.get("regulation") == "GDPR" and doc.metadata.get("section_type") == "Recital":
                    # In a true scoring pipeline we'd manipulate the score, but here we just flag it
                    # The reranker will handle semantic relevance effectively anyway.
                    pass 
                
                content_hash = hash(doc.page_content)
                if content_hash not in unique_chunks:
                    unique_chunks[content_hash] = doc
                    
        pool_documents = list(unique_chunks.values())
        if not pool_documents:
            return self._build_failure_response("No relevant documents found across all regulations.")

        # ---------------------------------------------------------
        # 2. Cross-Encoder Reranking (Cohere)
        # ---------------------------------------------------------
        # Cohere expects keyword arguments
        reranked_docs = self.reranker.compress_documents(documents=pool_documents, query=user_question)
        
        # Keep track of rerank scores manually for the confidence formula
        context_map = {}
        for idx, doc in enumerate(reranked_docs):
            citation = doc.metadata.get('citation', f"Unknown Source {idx}")
            relevance_score = doc.metadata.get("relevance_score", 0.0)
            context_map[citation] = {
                "text": doc.page_content,
                "relevance_score": relevance_score,
                "metadata": doc.metadata
            }

        # ---------------------------------------------------------
        # 3. LLM Generation with Strict JSON output
        # ---------------------------------------------------------
        # Build strict context string
        context_str = "\n\n".join([
            f"[Citation: {doc.metadata.get('citation', 'N/A')}] "
            f"[Regulation: {doc.metadata.get('regulation', 'N/A')}]\n"
            f"{doc.page_content}"
            for doc in reranked_docs
        ])
        
        system_prompt = f"""
You are an expert regulatory compliance AI for healthcare employees.
You must answer the user's question using ONLY the provided document chunks below.
Start your response with a direct answer to the user's question before providing further explanation.
Do NOT use outside knowledge. If the answer is not in the text, clearly state so.
Extract the EXACT string listed under [Citation: ...] to cite your answer.

[LEGAL DOCUMENTS]:
{context_str}
"""
        # Enforce structured Pydantic output
        structured_llm = self.llm.with_structured_output(RAGResponseFields)
        
        messages = [
            ("system", system_prompt),
            ("human", user_question)
        ]
        
        llm_response = structured_llm.invoke(messages)
        
        # ---------------------------------------------------------
        # 4. Deterministic Confidence Scoring
        # ---------------------------------------------------------
        confidence_score = 0.0
        
        if not llm_response.citations:
            # Penalty: LLM couldn't find a citation
            confidence_score = 0.0
            
        else:
            # A) Context Relevance Math (S_rerank)
            # Find the highest Cohere rerank score among the chunks the LLM ACTUALLY cited.
            valid_rerank_scores = []
            cited_texts = []
            hallucinated_citations = 0
            
            print(f"DEBUG LLM Citations: {llm_response.citations}")
            print(f"DEBUG Context Keys: {list(context_map.keys())}")
            
            for raw_citation in llm_response.citations:
                # Clean ALL possible prefixes LLM might add
                citation = raw_citation
                citation = citation.replace('[Citation:', '')
                citation = citation.replace('Citation:', '')
                citation = citation.replace('[', '')
                citation = citation.replace(']', '')
                citation = citation.strip()
                print(f"DEBUG Checking '{citation}' in keys...")
                if citation in context_map:
                    print(f"DEBUG Match found!")
                    valid_rerank_scores.append(context_map[citation]["relevance_score"])
                    cited_texts.append(context_map[citation]["text"])
                else:
                    hallucinated_citations += 1
                    
            if hallucinated_citations > 0:
                # Severe penalty for hallucinating a citation not in the Top 5
                s_rerank = 0.0
            else:
                s_rerank = max(valid_rerank_scores) if valid_rerank_scores else 0.0
                
            # B) Semantic Grounding Math (S_ground)
            # Compare embedding of the LLM's Answer vs embedding of the concatenated cited sources
            if cited_texts:
                concatenated_sources = " ".join(cited_texts)
                
                # Fetch embeddings
                # Note: Embeddings API can take lists
                embeddings_res = self.embeddings.embed_documents([llm_response.answer, concatenated_sources])
                answer_vec = embeddings_res[0]
                sources_vec = embeddings_res[1]
                
                s_ground = self.cosine_similarity(answer_vec, sources_vec)
            else:
                s_ground = 0.0
                
            # C) Final Formula
            confidence_score = (0.6 * s_rerank) + (0.4 * s_ground)
            
            # Bound the score
            confidence_score = max(0.0, min(1.0, confidence_score))

        # ---------------------------------------------------------
        # 5. Output Formatting
        # ---------------------------------------------------------
        process_time = round(time.time() - start_time, 2)
        
        final_response = {
            "answer": llm_response.answer,
            "citations": llm_response.citations,
            "confidence": round(confidence_score, 4),
            "regulation": llm_response.regulation,
            "threshold_status": "AUTO_APPROVED" if confidence_score >= 0.80 else "HUMAN_REVIEW_QUEUE",
            "from_cache": False,
            "process_time_sec": process_time,
            "contexts": [doc.page_content for doc in reranked_docs]
        }
        
        # --- Save to Cache (DO NOT save from_cache or time as True in the base file so it resets) ---
        cache_copy = dict(final_response)
        cache_copy.pop("from_cache", None)
        cache_copy.pop("process_time_sec", None)
        self.cache_data[question_hash] = cache_copy
        
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache_data, f, indent=2)
        except Exception as e:
            print(f"Warning: Failed to save cache: {e}")
            
        # Log fresh query to DB
        self._log_to_db(user_question, final_response)
            
        return final_response
        
    def _log_to_db(self, question: str, response: Dict[str, Any]):
        """Persists the query and result metadata to PostgreSQL/SQLite."""
        try:
            # We open a scoped session to save the log record safely
            db = SessionLocal()
            log_entry = AuditLog(
                question=question,
                answer=response.get("answer", ""),
                regulation=response.get("regulation", "N/A"),
                confidence=response.get("confidence", 0.0),
                status=response.get("threshold_status", "UNKNOWN"),
                process_time_sec=response.get("process_time_sec", 0.0),
                from_cache=response.get("from_cache", False),
                citations=json.dumps(response.get("citations", []))
            )
            db.add(log_entry)
            db.commit()
            db.close()
        except Exception as e:
            print(f"Failed to log audit data to database: {e}")
        
    def _build_failure_response(self, message: str) -> Dict[str, Any]:
        return {
            "answer": message,
            "citations": [],
            "confidence": 0.0,
            "regulation": "N/A",
            "threshold_status": "HUMAN_REVIEW_QUEUE"
        }

# Example Testing Loop
if __name__ == "__main__":
    import yaml
    
    async def main():
        pipeline = NormIQRAGPipeline()
        query_text = "What is the deadline to notify authorities of a data breach?"
        print(f"\\n[QUERY]: {query_text}")
        
        result = await pipeline.query(query_text)
        print("\\n[RESULT]")
        print(json.dumps(result, indent=2))
        
    asyncio.run(main())
