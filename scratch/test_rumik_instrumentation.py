import os
import time
import json
import asyncio
import requests
import websockets
from dotenv import load_dotenv
load_dotenv('/Users/raasikhnaveed/Desktop/dronav1project/.env')

from app.drona.voice_proxy import RUMIK_API_KEY, RUMIK_TTS_ENDPOINT, sanitize_secret

async def test_synthesize(text: str):
    t0 = time.time()
    rumik_key = RUMIK_API_KEY
    base_url = RUMIK_TTS_ENDPOINT

    print(f"\n=== BENCHMARKING RUMIK TTS SYNTHESIS FOR: '{text[:40]}...' ===")
    
    t_mint_start = time.time()
    resp = requests.post(
        f"{base_url}/v1/tts/ws-connect",
        headers={"Authorization": f"Bearer {rumik_key}", "Content-Type": "application/json"},
        json={"model": "mulberry", "text": text},
        timeout=10
    )
    t_mint_end = time.time()
    mint_ms = round((t_mint_end - t_mint_start) * 1000, 2)
    print(f"1. HTTP ws-connect Handshake Duration: {mint_ms} ms (Status {resp.status_code})")
    
    handshake_data = resp.json()
    ws_url = handshake_data["ws_url"]
    token = handshake_data["token"]

    pcm_bytes = bytearray()
    t_ws_start = time.time()
    
    t_first_byte = None
    
    async with websockets.connect(f"{ws_url}?token={token}") as ws:
        t_ws_connected = time.time()
        ws_connect_ms = round((t_ws_connected - t_ws_start) * 1000, 2)
        print(f"2. WebSocket Connect Duration: {ws_connect_ms} ms")
        
        await ws.send(json.dumps({
            "text": text,
            "speaker": "Ira"
        }))

        while True:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                if isinstance(msg, bytes):
                    if t_first_byte is None:
                        t_first_byte = time.time()
                        first_byte_ms = round((t_first_byte - t_ws_start) * 1000, 2)
                        print(f"3. Time to First PCM Byte (TTFB): {first_byte_ms} ms!")
                    pcm_bytes.extend(msg)
                elif isinstance(msg, str):
                    data = json.loads(msg)
                    print(f"   WS Text Control Frame received: {data}")
                    if data.get("type") in ("done", "complete", "finish", "end"):
                        print("   WS Done signal received!")
                        break
            except asyncio.TimeoutError:
                print("   WS Read Timeout (2.0s silence) -> Synthesis finished!")
                break

    t_total = time.time() - t0
    print(f"4. Total PCM Bytes Received: {len(pcm_bytes)} bytes (~{len(pcm_bytes)/(24000*2):.2f} seconds of 24kHz audio)")
    print(f"5. Total Per-Sentence TTS Duration: {t_total:.2f} seconds!")

if __name__ == "__main__":
    asyncio.run(test_synthesize("Bilkul sahi! Aapne exact mechanism pakda hai."))
