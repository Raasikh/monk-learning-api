import requests
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

key = "sk_em0ijw2w_lDCzrYyfuAmNbqlaPATDMpIg"

# Test HTTP POST to https://api.sarvam.ai/speech-to-text
resp = requests.post(
    "https://api.sarvam.ai/speech-to-text",
    headers={"api-subscription-key": key},
    data={"model": "saaras:v3"}
)

print("Sarvam HTTP response status:", resp.status_code)
print("Sarvam HTTP response body:", resp.text[:300])
