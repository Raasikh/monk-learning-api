import asyncio
import websockets
import urllib.request
import json
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

SARVAM_KEY = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

# Check HTTP GET/POST response body for detailed 403 reason
req = urllib.request.Request(
    "https://api.sarvam.ai/speech-to-text-translate-ws",
    headers={"api-subscription-key": SARVAM_KEY}
)

try:
    with urllib.request.urlopen(req) as response:
        print("Response:", response.status, response.read())
except urllib.error.HTTPError as e:
    print("HTTP Error Code:", e.code)
    print("HTTP Error Body:", e.read().decode())
except Exception as exc:
    print("Error:", exc)
