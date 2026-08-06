import os
import asyncio
import logging
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.drona.voice_proxy import SaarasSTTProxy

async def main():
    print("=== TESTING SARVAM SAARAS STT V3 WEBSOCKET STREAMING ===")
    proxy = SaarasSTTProxy(mode="codemix", latency_profile="Fast")

    # Generate 3 seconds of dummy PCM audio (16kHz 16-bit mono = 32000 bytes/sec)
    async def dummy_pcm_generator():
        pcm_chunk = b"\x00\x00" * 1600 # 3200 bytes = 100ms
        for i in range(30): # 3 seconds
            yield pcm_chunk
            await asyncio.sleep(0.1)

    def on_transcript(raw: str, norm: str, is_final: bool, conf: float):
        print(f"🎯 [SARVAM CALLBACK] raw='{raw}', norm='{norm}', is_final={is_final}, conf={conf}")

    def on_barge_in():
        print("⚡ [SARVAM BARGE-IN DETECTED]")

    try:
        await proxy.connect_and_stream(dummy_pcm_generator(), on_transcript, on_barge_in)
    except Exception as e:
        print(f"❌ SARVAM STT ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(main())
