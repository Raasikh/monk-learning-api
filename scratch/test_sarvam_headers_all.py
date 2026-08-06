import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

# Sarvam WebSocket endpoints and header combinations
endpoints = [
    "wss://api.sarvam.ai/speech-to-text-translate-ws",
    "wss://api.sarvam.ai/speech-to-text-ws",
    "wss://api.sarvam.ai/v1/speech-to-text-translate-ws",
    "wss://api.sarvam.ai/v1/speech-to-text-ws",
    "wss://api.sarvam.ai/streaming/speech-to-text",
    "wss://api.sarvam.ai/streaming/speech-to-text-translate"
]

async def test():
    for ep in endpoints:
        url = f"{ep}?model=saaras:v3&mode=codemix"
        headers = {
            "api-subscription-key": SARVAM_KEY,
            "User-Agent": "Python/3.11 websockets"
        }
        print(f"Testing {ep}...")
        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                print(f"🎉 SUCCESS! Connected to {ep}")
                return True
        except Exception as e:
            print(f"  Failed ({ep}): {e}")

if __name__ == "__main__":
    asyncio.run(test())
