#!/usr/bin/env python3
"""
Extract text from PTS PDF documents and organize them in compliance_kb.
Creates structured knowledge base for agents to reference.
"""

import pdfplumber
import json
from pathlib import Path
from datetime import datetime, timezone


# Mapping of PDF files to KB categories and descriptions
PDF_MAPPING = {
    "TekniskaKravTotalRapport.pdf": {
        "category": "tekniska_krav",
        "type": "technical_requirements",
        "title": "Tekniska Krav Total Rapport",
        "description": "Total report of technical requirements from PTS",
        "relevant_agents": ["compliance", "architect", "mep"]
    },
    "FunktionskravPdf.pdf": {
        "category": "funktionskrav",
        "type": "functional_requirements",
        "title": "Funktionskrav",
        "description": "Functional requirements for rooms and spaces",
        "relevant_agents": ["brief", "architect"]
    },
    "Miljokravrapport.pdf": {
        "category": "miljokrav",
        "type": "environmental_requirements",
        "title": "Miljökrav Rapport",
        "description": "Environmental and sustainability requirements",
        "relevant_agents": ["compliance", "architect"]
    },
    "TyprumPdf.pdf": {
        "category": "typrum",
        "type": "room_types",
        "title": "Typrum (Rumstyper)",
        "description": "Standard room types with dimensions and specifications",
        "relevant_agents": ["brief", "architect"]
    },
    "YtskiktPdf.pdf": {
        "category": "ytskikt",
        "type": "surface_materials",
        "title": "Ytskikt och Material",
        "description": "Surface materials and finishes specifications",
        "relevant_agents": ["architect", "compliance"]
    },
    "riktlinje-brand-gaevleborg.pdf": {
        "category": "brand",
        "type": "fire_safety",
        "title": "Riktlinje Brand Gävleborg",
        "description": "Fire safety guidelines for Gävleborg region",
        "relevant_agents": ["compliance", "architect"]
    }
}


def extract_pdf_text(pdf_path: Path) -> str:
    """Extract all text from PDF file."""
    text = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_text = page.extract_text()
                if page_text:
                    text.append(f"\n--- Page {page_num} ---\n{page_text}")
    except Exception as e:
        print(f"Error extracting {pdf_path.name}: {e}")
        return ""
    
    return "\n".join(text)


def organize_kb():
    """Extract PDFs and organize into compliance_kb structure."""
    docs_dir = Path("docs")
    kb_base = Path("compliance_kb/SE/healthcare")
    kb_base.mkdir(parents=True, exist_ok=True)
    
    # Create index
    index = {
        "jurisdiction": "SE",
        "region": "Gävleborg",
        "building_type": "healthcare",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "documents": {}
    }
    
    for pdf_file, metadata in PDF_MAPPING.items():
        pdf_path = docs_dir / pdf_file
        if not pdf_path.exists():
            print(f"⚠️  Missing: {pdf_file}")
            continue
        
        print(f"📄 Extracting: {pdf_file}...")
        
        # Extract text
        text_content = extract_pdf_text(pdf_path)
        
        if not text_content.strip():
            print(f"  ⚠️  No text extracted from {pdf_file}")
            continue
        
        # Save to file
        category = metadata["category"]
        out_file = kb_base / f"{category}.txt"
        out_file.write_text(text_content, encoding="utf-8")
        
        # Create JSON metadata for the document
        meta_file = kb_base / f"{category}.meta.json"
        meta = {
            "filename": pdf_file,
            "category": category,
            "type": metadata["type"],
            "title": metadata["title"],
            "description": metadata["description"],
            "relevant_agents": metadata["relevant_agents"],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
            "text_file": f"{category}.txt",
            "char_count": len(text_content)
        }
        meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        
        index["documents"][category] = {
            "title": metadata["title"],
            "type": metadata["type"],
            "agents": metadata["relevant_agents"],
            "text_file": f"{category}.txt",
            "meta_file": f"{category}.meta.json",
            "char_count": len(text_content)
        }
        
        print(f"  ✅ Saved {len(text_content):,} characters")
    
    # Save index
    index_file = kb_base / "index.json"
    index_file.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✅ Knowledge base index saved to {index_file}")
    
    # Create loader helper
    create_kb_loader(kb_base)
    
    return kb_base


def create_kb_loader(kb_dir: Path):
    """Create a simple Python module to load KB documents."""
    loader_code = '''"""
Knowledge Base Loader — helps agents access PTS documents.
Auto-generated by extract_pdf_kb.py
"""

import json
from pathlib import Path
from typing import Optional, Dict

class KnowledgeBaseLoader:
    def __init__(self, kb_dir: Path = None):
        if kb_dir is None:
            kb_dir = Path(__file__).parent / "SE/healthcare"
        self.kb_dir = Path(kb_dir)
        self.index = self._load_index()
    
    def _load_index(self) -> dict:
        """Load the KB index."""
        index_file = self.kb_dir / "index.json"
        if index_file.exists():
            return json.loads(index_file.read_text(encoding="utf-8"))
        return {}
    
    def get_document(self, category: str) -> Optional[str]:
        """Load a single document by category."""
        doc_meta = self.index.get("documents", {}).get(category)
        if not doc_meta:
            return None
        text_file = self.kb_dir / doc_meta["text_file"]
        if text_file.exists():
            return text_file.read_text(encoding="utf-8")
        return None
    
    def get_documents_for_agent(self, agent_id: str) -> Dict[str, str]:
        """Load all documents relevant to a specific agent."""
        result = {}
        for category, doc_meta in self.index.get("documents", {}).items():
            if agent_id in doc_meta.get("agents", []):
                content = self.get_document(category)
                if content:
                    result[category] = content
        return result
    
    def get_prompt_context(self, agent_id: str) -> str:
        """Get formatted KB context for system prompt."""
        docs = self.get_documents_for_agent(agent_id)
        if not docs:
            return ""
        
        lines = ["\\n### REGULATORY KNOWLEDGE BASE (PTS Documents)\\n"]
        for category, content in docs.items():
            lines.append(f"\\n#### {category.upper()}\\n")
            lines.append(content[:2000])  # Truncate to first 2000 chars per doc
            if len(content) > 2000:
                lines.append("\\n[... document truncated for context length ...]\\n")
        
        return "\\n".join(lines)

# Singleton instance
_loader = None

def get_loader(kb_dir: Path = None) -> KnowledgeBaseLoader:
    global _loader
    if _loader is None:
        _loader = KnowledgeBaseLoader(kb_dir)
    return _loader
'''
    
    loader_file = Path("src/memory/kb_loader.py")
    loader_file.write_text(loader_code, encoding="utf-8")
    print(f"✅ KB loader module created at {loader_file}")


if __name__ == "__main__":
    kb_dir = organize_kb()
    print(f"\n✨ Knowledge base organized in: {kb_dir}")
    print("\nAgents can now load KB documents using:")
    print("  from src.memory.kb_loader import get_loader")
    print("  loader = get_loader()")
    print("  context = loader.get_prompt_context('brief')")
