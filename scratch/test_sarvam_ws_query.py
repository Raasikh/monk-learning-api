import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

urls = [
    f"wss://api.sarvam.ai/speech-to-text-ws?api-subscription-key={SARVAM_KEY}&model=saaras:v3&mode=codemix",
    f"wss://api.sarvam.ai/speech-to-text-translate-ws?api-subscription-key={SARVAM_KEY}&model=saaras:v3&mode=codemix",
    f"wss://api.sarvam.ai/speech-to-text-ws?subscription-key={SARVAM_KEY}&model=saaras:v3&mode=codemix"
]

async def test():
    for u in urls:
        print(f"Testing WS URL: {u[:60]}...")
        try:
            async with websockets.connect(u) as ws:
                print(f"🎉 SUCCESS! Connected to Sarvam WebSocket: {u[:60]}")
                return True
        except Exception as e:
            print(f"❌ Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test())
