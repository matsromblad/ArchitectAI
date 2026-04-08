import os
import base64
import json
import urllib.request
import ssl
from dotenv import load_dotenv

load_dotenv()

def test_vision_rest():
    api_key = os.getenv("GEMINI_API_KEY")
    model = "models/gemini-3.1-flash-lite-preview"
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={api_key}"
    
    # Simple 1x1 PNG red dot
    image_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"inline_data": {"mime_type": "image/png", "data": image_b64}},
                    {"text": "Describe this image."}
                ]
            }
        ]
    }
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    print(f"Testing Vision REST to {model}...")
    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            raw = resp.read()
            print(f"Response size: {len(raw)} bytes")
            print(f"First 10 bytes: {raw[:10]}")
            data = json.loads(raw.decode())
            print("Response text:", data["candidates"][0]["content"]["parts"][0]["text"])
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'read'):
            err = e.read()
            print(f"Error raw: {err[:100]}")
            try:
                print(f"Error decoded: {err.decode()}")
            except:
                print("Could not decode error as utf-8")

if __name__ == "__main__":
    test_vision_rest()
