import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
from time import perf_counter
import logging
import json

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self):
        self.client = chromadb.PersistentClient()  # Replace the old Settings()-based initialization
        self.collection = self.client.get_or_create_collection("loan_documents")
    
    def store_document(self, document_info: Dict[str, Any], document_id: str):
        start = perf_counter()
        if not document_id:
            raise ValueError("document_id cannot be None or empty")
            
        text_content = json.dumps(document_info)
        self.collection.add(
            documents=[text_content],
            metadatas=[document_info],
            ids=[document_id]
        )
        logger.info(f"⏱️ Document storage took {perf_counter() - start:.2f} seconds")
    
    def search_documents(self, query: str, n_results: int = 10) -> List[Dict[str, Any]]:
        start = perf_counter()
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            logger.info(f"⏱️ Document search took {perf_counter() - start:.2f} seconds")
            return results['metadatas'][0] if results['metadatas'] else []
        except Exception as e:
            logger.error(f"Error searching documents: {e}")
            return []
    
    def check_if_document_exists(self, document_id: str) -> bool:
        if not document_id:
            return False
            
        try:
            result = self.index.fetch(ids=[document_id])
            return len(result.vectors) > 0
        except Exception:
            return False
    
    def update_document(self, document_info: Dict[str, Any], document_id: str):
        if not document_id:
            raise ValueError("document_id cannot be None or empty")
        self.collection.remove(document_id)
        self.store_document(document_info, document_id)