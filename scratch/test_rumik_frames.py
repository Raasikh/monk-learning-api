from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.drona.voice_proxy import RumikTTSProxy

async def main():
    proxy = RumikTTSProxy(voice_preset="Ira", model="mulberry")
    text = "Thermodynamics mein system and surroundings bohot important hotey hain."
    print(f"=== TESTING RUMIK TTS SYNTHESIS FOR TEXT: '{text}' ===")
    try:
        pcm = await proxy.synthesize_text(text)
        print(f"SUCCESS! Received {len(pcm)} PCM bytes.")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    asyncio.run(main())
