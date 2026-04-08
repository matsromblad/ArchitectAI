import os
import urllib.request
import json
import ssl
from dotenv import load_dotenv

load_dotenv()

def list_models_rest():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("No GEMINI_API_KEY found")
        return

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    
    print(f"Direct REST call: {url}")
    
    # Disable SSL verification for quick diagnostic (local dev context)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(url, context=ctx) as response:
            data = json.loads(response.read().decode())
            print("Successfully reached API!")
            for m in data.get('models', []):
                if 'generateContent' in m.get('supportedGenerationMethods', []):
                    print(f"- {m['name']} ({m['displayName']})")
    except Exception as e:
        print(f"REST call failed: {e}")
        if hasattr(e, 'read'):
            print("Error details:", e.read().decode())

if __name__ == "__main__":
    list_models_rest()
