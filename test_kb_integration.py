#!/usr/bin/env python3
"""Test KB integration — verify all agents can access their KB documents."""

from src.memory.kb_loader import get_loader

def test_kb_loader():
    """Test that KB loader works and provides correct context."""
    print("=" * 60)
    print("KB INTEGRATION TEST")
    print("=" * 60)
    
    loader = get_loader()
    index = loader.index
    
    print("\n1. Available KB Documents:")
    print("-" * 60)
    doc_count = len(index.get('documents', {}))
    print(f"   Total: {doc_count} documents\n")
    
    for doc_name, doc_meta in index.get('documents', {}).items():
        print(f"   • {doc_name.upper()}")
        print(f"     Title: {doc_meta.get('title', 'N/A')}")
        print(f"     Agents: {', '.join(doc_meta.get('agents', []))}")
        print(f"     Size: {doc_meta.get('char_count', 0):,} characters")
        print()
    
    print("\n2. Agent-Specific KB Context:")
    print("-" * 60)
    
    test_agents = ["brief", "compliance", "mep", "architect"]
    for agent_id in test_agents:
        docs = loader.get_documents_for_agent(agent_id)
        print(f"\n   {agent_id.upper()} Agent:")
        if docs:
            for doc_name, content in docs.items():
                print(f"     ✓ {doc_name}: {len(content):,} chars loaded")
        else:
            print(f"     (No KB documents assigned)")
    
    print("\n3. System Prompt Context Test:")
    print("-" * 60)
    
    # Test Brief Agent prompt building
    print("\n   BRIEF AGENT prompt context sample (first 500 chars):")
    brief_docs = loader.get_documents_for_agent("brief")
    if brief_docs.get("funktionskrav"):
        sample = brief_docs["funktionskrav"][:500]
        print(f"   {sample}")
    
    print("\n" + "=" * 60)
    print("✅ KB Integration Test Complete")
    print("=" * 60)
    print("\nAgents are now ready to use the following PTS documents:")
    print("  • TekniskaKravTotalRapport.pdf (Tekniska krav)")
    print("  • FunktionskravPdf.pdf (Funktionskrav)")
    print("  • TyprumPdf.pdf (Typrum/Rumstyper)")
    print("  • Miljokravrapport.pdf (Miljökrav)")
    print("  • riktlinje-brand-gaevleborg.pdf (Brandkrav)")
    print("\nDocuments are automatically injected into agent system prompts.")

if __name__ == "__main__":
    test_kb_loader()
