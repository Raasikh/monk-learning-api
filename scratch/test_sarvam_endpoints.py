import asyncio
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

endpoints = [
    "wss://api.sarvam.ai/speech-to-text-ws",
    "wss://api.sarvam.ai/speech-to-text-translate-ws",
    "wss://api.sarvam.ai/v1/speech-to-text-ws"
]

async def test_endpoint(url):
    headers = {"api-subscription-key": SARVAM_KEY}
    params = f"?model=saaras:v3&mode=codemix&latency=Fast"
    full_url = f"{url}{params}"
    print(f"Testing {full_url}...")
    try:
        async with websockets.connect(full_url, additional_headers=headers) as ws:
            print(f"🎉 SUCCESS! Connected to {url}!")
            return True
    except Exception as e:
        print(f"❌ Failed connecting to {url}: {e}")
        return False

async def main():
    for ep in endpoints:
        if await test_endpoint(ep):
            break

if __name__ == "__main__":
    asyncio.run(main())
