import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

endpoints = [
    "wss://api.sarvam.ai/speech-to-text-translate-ws",
    "wss://api.sarvam.ai/speech-to-text-ws"
]

param_combos = [
    "",
    "?model=saaras:v3",
    "?model=saaras:v3&language_code=hi-IN",
    "?model=saaras:v3&mode=codemix",
    "?model=saaras-v2&language_code=hi-IN",
    "?model=saaras:v1",
    "?model=saaras:v3&encoding=linear16&sample_rate=16000",
    "?model=saaras:v3&mode=codemix&latency=Fast&encoding=linear16"
]

async def test():
    headers = {"api-subscription-key": SARVAM_KEY}
    for ep in endpoints:
        for p in param_combos:
            url = f"{ep}{p}"
            try:
                print(f"Testing {url}...")
                async with websockets.connect(url, additional_headers=headers) as ws:
                    print(f"🎉 SUCCESS! Connected to {url}")
                    return True
            except Exception as e:
                pass
    return False

if __name__ == "__main__":
    asyncio.run(test())
