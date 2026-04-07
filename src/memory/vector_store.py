"""
Vector Store — provides semantic search for regulatory documents using ChromaDB.
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
from loguru import logger

class VectorStore:
    """
    Wraps ChromaDB to provide semantic search for the Knowledge Base.
    Used by agents to find relevant clauses in large regulatory documents.
    """

    def __init__(self, persist_directory: str = None):
        if persist_directory is None:
            # Default to compliance_kb/vector_index
            persist_directory = str(Path("compliance_kb") / "vector_index")
        
        self.persist_directory = persist_directory
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        
        # Use default embedding function (all-MiniLM-L6-v2)
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        
        # Create or get the collection
        self.collection = self.client.get_or_create_collection(
            name="pts_regulations",
            embedding_function=self.ef,
            metadata={"description": "PTS Healthcare Regulations for Sweden"}
        )

    def add_documents(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]):
        """
        Add text chunks to the vector store.
        """
        if not ids:
            return
        
        logger.info(f"[VectorStore] Adding {len(documents)} chunks to index")
        
        # Batching for large imports
        batch_size = 100
        for i in range(0, len(ids), batch_size):
            end = min(i + batch_size, len(ids))
            self.collection.add(
                ids=ids[i:end],
                documents=documents[i:end],
                metadatas=metadatas[i:end]
            )

    def query(self, text: str, n_results: int = 5, where: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Search for the most relevant chunks.
        
        Args:
            text: Query string.
            n_results: Number of chunks to return.
            where: Metadata filter (e.g., {"category": "typrum"}).
            
        Returns:
            List of dicts with 'document', 'metadata', and 'id'.
        """
        results = self.collection.query(
            query_texts=[text],
            n_results=n_results,
            where=where
        )
        
        formatted = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                formatted.append({
                    "id": results["ids"][0][i],
                    "document": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i] if results.get("distances") else None
                })
        
        return formatted

    def get_count(self) -> int:
        """Return the number of items in the collection."""
        return self.collection.count()

    def clear(self):
        """Delete all items in the collection."""
        self.client.delete_collection("pts_regulations")
        self.collection = self.client.get_or_create_collection(
            name="pts_regulations",
            embedding_function=self.ef
        )

# Singleton access
_vector_store = None

def get_vector_store(persist_directory: str = None) -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(persist_directory)
    return _vector_store
