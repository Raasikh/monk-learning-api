import time
import io
import wave
import requests
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

def measure_rest_stt_latency():
    print("=== MEASURING SARVAM REST STT LATENCY ACROSS 5 UTTERANCE DURATIONS ===")
    durations = [2, 5, 10, 15, 20]
    results = []

    headers = {"api-subscription-key": SARVAM_KEY}
    url = "https://api.sarvam.ai/speech-to-text"

    for d in durations:
        # Generate d seconds of 16kHz 16-bit PCM WAV audio
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(b'\x00\x10\x00\xf0' * (16000 * d // 2))
        buf.seek(0)
        wav_bytes = buf.read()
        byte_count = len(wav_bytes)

        files = {'file': (f'speech_{d}s.wav', io.BytesIO(wav_bytes), 'audio/wav')}
        data = {'model': 'saaras:v3', 'mode': 'codemix', 'language_code': 'hi-IN'}

        t_start = time.time()
        resp = requests.post(url, headers=headers, data=data, files=files, timeout=15)
        t_end = time.time()

        latency_ms = (t_end - t_start) * 1000.0
        status = resp.status_code
        transcript = resp.json().get("transcript", "") if status == 200 else ""

        print(f"Duration: {d:2d}s | Bytes: {byte_count:7d} | Status: {status} | Latency: {latency_ms:6.1f} ms | Transcript: '{transcript}'")
        results.append((d, byte_count, latency_ms, status, transcript))

    print("\n=== LATENCY BENCHMARK SUMMARY TABLE ===")
    print("| Duration (s) | Payload Size | HTTP Status | Measured Latency (ms) |")
    print("|--------------|--------------|-------------|-----------------------|")
    for d, bytes_cnt, lat, stat, _ in results:
        print(f"| {d:2d}s          | {bytes_cnt:7d} B    | {stat}         | {lat:6.1f} ms             |")

if __name__ == "__main__":
    measure_rest_stt_latency()
