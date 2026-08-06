import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

headers_variants = [
    {"api-subscription-key": SARVAM_KEY},
    {"api-subscription-key": SARVAM_KEY, "Content-Type": "audio/l16"},
    {"api-subscription-key": SARVAM_KEY, "api-key": SARVAM_KEY},
    {"Authorization": f"Bearer {SARVAM_KEY}"},
    {"x-api-key": SARVAM_KEY}
]

url = "wss://api.sarvam.ai/speech-to-text-translate-ws?model=saaras:v3&mode=codemix&latency=Fast"

async def test():
    for h in headers_variants:
        print(f"Testing headers: {list(h.keys())}...")
        try:
            async with websockets.connect(url, additional_headers=h) as ws:
                print(f"🎉 SUCCESS! Connected with headers: {list(h.keys())}")
                return True
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test())
