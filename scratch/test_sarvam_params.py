import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

models = ["saaras:v3", "saaras-v3", "saaras:v2", "saaras-v2", "saaras:v1", "saaras"]
endpoints = ["wss://api.sarvam.ai/speech-to-text-translate-ws", "wss://api.sarvam.ai/speech-to-text-ws"]

async def test():
    for ep in endpoints:
        for m in models:
            url = f"{ep}?model={m}&sample_rate=16000&mode=codemix"
            headers = {"api-subscription-key": SARVAM_KEY}
            try:
                print(f"Testing model={m} on {ep}...")
                async with websockets.connect(url, additional_headers=headers) as ws:
                    print(f"🎉 SUCCESS! Connected with model={m} on {ep}!")
                    return True
            except Exception as e:
                pass
    return False

if __name__ == "__main__":
    asyncio.run(test())
