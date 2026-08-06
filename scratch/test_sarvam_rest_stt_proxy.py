from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

import asyncio
import io
import wave
import json
import logging
import requests

from app.drona.voice_proxy import normalize_devanagari_to_roman

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

def transcribe_pcm_chunks(pcm_chunks: list[bytes], model: str = "saaras:v3", mode: str = "codemix") -> str:
    all_bytes = b"".join(pcm_chunks)
    if len(all_bytes) < 3200: # Less than 100ms
        return ""

    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(all_bytes)
    buf.seek(0)

    files = {'file': ('speech.wav', buf, 'audio/wav')}
    data = {'model': model, 'mode': mode, 'language_code': 'hi-IN'}
    headers = {'api-subscription-key': SARVAM_KEY}

    resp = requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files, timeout=10)
    if resp.status_code == 200:
        res_data = resp.json()
        raw = res_data.get("transcript", "")
        norm = normalize_devanagari_to_roman(raw)
        print(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw}', norm='{norm}', is_final=True")
        return norm
    else:
        print(f"❌ [SARVAM STT REST ERROR] HTTP {resp.status_code}: {resp.text}")
        return ""

if __name__ == "__main__":
    print("Testing transcribe_pcm_chunks with dummy silence audio...")
    dummy_chunks = [b'\x00\x00' * 16000] # 1s silence
    res = transcribe_pcm_chunks(dummy_chunks)
    print("Transcribed result:", res)
