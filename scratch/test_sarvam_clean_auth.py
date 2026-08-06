import asyncio
import websockets
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

endpoints = [
    "wss://api.sarvam.ai/speech-to-text-ws",
    "wss://api.sarvam.ai/speech-to-text-translate-ws",
    "wss://api.sarvam.ai/v1/speech-to-text-ws"
]

async def test():
    headers = {"api-subscription-key": SARVAM_KEY}
    for ep in endpoints:
        url = f"{ep}?model=saaras:v3&mode=codemix&sample_rate=16000"
        print(f"Testing {url} with single api-subscription-key header...")
        try:
            async with websockets.connect(url, additional_headers=headers) as ws:
                print(f"🎉 SUCCESS! Connected to {ep}!")
                return True
        except websockets.exceptions.InvalidStatusCode as err:
            print(f"  ❌ Failed ({ep}): HTTP {err.status_code} - {err}")
        except Exception as err:
            print(f"  ❌ Exception ({ep}): {err}")
    return False

if __name__ == "__main__":
    asyncio.run(test())
