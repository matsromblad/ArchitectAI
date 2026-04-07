from src.memory.kb_loader import get_loader

def test_rag():
    loader = get_loader()
    
    # Search for something that should be in typrum.txt
    query = "Akutrum dimensioner och krav"
    print(f"Testing RAG with query: '{query}'")
    
    context = loader.get_semantic_context(query, "brief", n_results=2)
    print("\nRETRIEVED CONTEXT:")
    print(context)
    
    if "Akutrum" in context:
        print("\nSUCCESS: Found relevant text!")
    else:
        print("\nFAILURE: Context did not contain 'Akutrum'")

if __name__ == "__main__":
    test_rag()
