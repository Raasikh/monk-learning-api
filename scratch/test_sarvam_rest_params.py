import requests
import io
import wave
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

def test_rest_params():
    print("=== TESTING SARVAM REST PARAMETERS & ENDPOINTS ===")
    
    # 1. Create a dummy 1-second audio WAV buffer
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x00\x10\x00\xf0' * 8000) # 1s non-zero pcm
    buf.seek(0)
    wav_bytes = buf.read()

    endpoints = [
        "https://api.sarvam.ai/speech-to-text",
        "https://api.sarvam.ai/speech-to-text-translate"
    ]

    param_sets = [
        {"model": "saaras:v3", "mode": "codemix", "language_code": "hi-IN"},
        {"model": "saaras:v3", "mode": "codemix", "language_code": "en-IN"},
        {"model": "saaras:v3", "language_code": "unknown"},
        {"model": "saaras:v3", "with_diacritics": "false"},
        {"model": "saaras:v2", "language_code": "hi-IN"}
    ]

    headers = {"api-subscription-key": SARVAM_KEY}

    for ep in endpoints:
        for p in param_sets:
            files = {'file': ('test.wav', io.BytesIO(wav_bytes), 'audio/wav')}
            print(f"POST {ep} with params: {p}...")
            try:
                resp = requests.post(ep, headers=headers, data=p, files=files, timeout=5)
                print(f"  Status: {resp.status_code}, Body: {resp.text[:200]}")
            except Exception as e:
                print(f"  Error: {e}")

if __name__ == "__main__":
    test_rest_params()
