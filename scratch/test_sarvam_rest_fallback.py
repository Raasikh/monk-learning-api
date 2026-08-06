import requests
import io
import wave
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

def test_rest_stt():
    print("=== TESTING SARVAM REST STT WITH DUMMY WAV AUDIO ===")
    
    # Create 1 second 16kHz mono WAV file in memory
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b'\x00\x00' * 16000)
    buf.seek(0)

    files = {
        'file': ('sample.wav', buf, 'audio/wav')
    }
    data = {
        'model': 'saaras:v3',
        'mode': 'codemix',
        'language_code': 'hi-IN'
    }
    headers = {
        'api-subscription-key': SARVAM_KEY
    }

    resp = requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files)
    print("Sarvam REST STT Status Code:", resp.status_code)
    print("Sarvam REST STT Response:", resp.text)

if __name__ == "__main__":
    test_rest_stt()
