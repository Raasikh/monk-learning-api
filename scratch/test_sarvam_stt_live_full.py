from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

import os
import sys
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.drona.voice_proxy import SaarasSTTProxy

async def test_full_stt():
    print("=== TESTING SARVAM STT PROXY END-TO-END WITH AUDIO STREAM ===")
    proxy = SaarasSTTProxy(mode="codemix")

    # Generate 2 seconds of 16kHz 16-bit PCM audio (32000 bytes/sec)
    async def sample_pcm_stream():
        chunk = b"\x00\x10\x00\xf0" * 800 # 3200 bytes = 100ms
        for i in range(20): # 2.0 seconds
            yield chunk
            await asyncio.sleep(0.05)

    def on_transcript(raw: str, norm: str, is_final: bool, conf: float):
        print(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw}', norm='{norm}', is_final={is_final}, confidence={conf}")

    def on_barge_in():
        print("⚡ [SARVAM BARGE-IN DETECTED]")

    await proxy.connect_and_stream(sample_pcm_stream(), on_transcript, on_barge_in)

if __name__ == "__main__":
    asyncio.run(test_full_stt())
