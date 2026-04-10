#!/usr/bin/env python3
"""
Vectorize the Knowledge Base — chunks PTS text files and stores them in ChromaDB.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path so 'src' imports work when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import re
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from loguru import logger
from src.memory.vector_store import get_vector_store

def chunk_text(text: str, source_name: str, category: str) -> List[Dict[str, Any]]:
    """
    Chunks text by page separators '--- Page X ---'.
    Falls back to fixed-size chunking if no separators found.
    """
    chunks = []
    
    # Try splitting by page
    page_splits = re.split(r'--- Page (\d+) ---', text)
    
    if len(page_splits) > 1:
        # re.split with capturing group returns [prefix, page1_num, page1_content, page2_num, page2_content, ...]
        # skip prefix if empty
        start_idx = 1 if page_splits[0].strip() == "" else 0
        
        current_page = "0"
        for i in range(start_idx, len(page_splits)):
            part = page_splits[i].strip()
            if not part:
                continue
            
            if part.isdigit():
                current_page = part
            else:
                # This is page content
                # Try to extract a title (first non-empty line after "Typrum" or similar)
                lines = [l.strip() for l in part.split('\n') if l.strip()]
                title = "Unknown"
                if lines:
                    # Specific heuristic for PTS Typrum docs
                    if len(lines) > 2 and "Typrum" in lines[0]:
                         title = lines[2] # Often the room name is on line 3
                    else:
                         title = lines[0][:100]
                
                chunks.append({
                    "content": part,
                    "metadata": {
                        "source": source_name,
                        "category": category,
                        "page": current_page,
                        "title": title
                    }
                })
    else:
        # Fallback: Fixed size chunking with overlap
        chunk_size = 2000
        overlap = 200
        for i in range(0, len(text), chunk_size - overlap):
            content = text[i:i + chunk_size].strip()
            if not content:
                continue
            chunks.append({
                "content": content,
                "metadata": {
                    "source": source_name,
                    "category": category,
                    "page": "N/A",
                    "title": f"{source_name} (Part {i//chunk_size})"
                }
            })
            
    return chunks

def run_vectorization():
    kb_dir = Path("compliance_kb/SE/healthcare")
    index_file = kb_dir / "index.json"
    
    if not index_file.exists():
        logger.error(f"KB index not found at {index_file}. Run extract_pdf_kb.py first.")
        return

    index = json.loads(index_file.read_text(encoding="utf-8"))
    vector_store = get_vector_store()
    
    # Clear existing index to avoid duplicates during re-runs
    logger.info("Clearing existing vector index...")
    vector_store.clear()
    
    all_chunks = []
    
    for category, doc_meta in index.get("documents", {}).items():
        text_file = kb_dir / doc_meta["text_file"]
        if not text_file.exists():
            logger.warning(f"Text file {text_file} not found, skipping...")
            continue
        
        logger.info(f"Processing {category} ({doc_meta['title']})...")
        text = text_file.read_text(encoding="utf-8")
        
        chunks = chunk_text(text, doc_meta["title"], category)
        all_chunks.extend(chunks)
        logger.info(f"  Created {len(chunks)} chunks")

    # Add to vector store
    ids = [f"chunk_{i:04d}" for i in range(len(all_chunks))]
    documents = [c["content"] for c in all_chunks]
    metadatas = [c["metadata"] for c in all_chunks]
    
    vector_store.add_documents(ids, documents, metadatas)
    
    logger.success(f"Vectorization complete! Total chunks in index: {vector_store.get_count()}")

if __name__ == "__main__":
    run_vectorization()
