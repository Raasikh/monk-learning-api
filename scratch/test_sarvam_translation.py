import requests
import io
import wave
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

def test_translation():
    # Create 1 second audio WAV buffer
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x00\x10\x00\xf0' * 8000)
    buf.seek(0)
    wav_bytes = buf.read()

    headers = {"api-subscription-key": SARVAM_KEY}

    payloads = [
        {"model": "saaras:v3", "target_language_code": "en-IN"},
        {"model": "saaras:v3", "prompt": "Transcribe to Hinglish in Latin script"},
        {"model": "saaras:v3-realtime", "mode": "codemix"}
    ]

    for p in payloads:
        files = {'file': ('test.wav', io.BytesIO(wav_bytes), 'audio/wav')}
        resp = requests.post("https://api.sarvam.ai/speech-to-text-translate", headers=headers, data=p, files=files)
        print(f"Payload: {p}")
        print(f"Status: {resp.status_code}, Body: {resp.text[:250]}")

if __name__ == "__main__":
    test_translation()
