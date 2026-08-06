import os
import re
import json
import time
import asyncio
import base64
import logging
import requests
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple
import websockets

logger = logging.getLogger("drona.voice_proxy")

# Fixed Base Endpoints (Constant across environments)
RUMIK_TTS_ENDPOINT = "https://silk-api.rumik.ai"
SARVAM_STT_ENDPOINT = "wss://api.sarvam.ai/speech-to-text-ws"
SARVAM_STT_REST_ENDPOINT = "https://api.sarvam.ai/speech-to-text"

# Read API Keys strictly without silent fallbacks
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip("\"'")
RUMIK_API_KEY = os.environ.get("RUMIK_API_KEY", "").strip("\"'")

# Secret Redacting Regular Expressions
SECRET_PATTERNS = [
    re.compile(r'rk_live_[A-Za-z0-9_\-]+'),
    re.compile(r'sk_[A-Za-z0-9_\-]+'),
    re.compile(r'Bearer\s+[A-Za-z0-9_\-\.\=]+', re.IGNORECASE),
]

def sanitize_secret(text: str) -> str:
    """Sanitizes sensitive keys and bearer tokens from logs and exception messages."""
    if not text:
        return ""
    res = str(text)
    for pat in SECRET_PATTERNS:
        res = pat.sub("***REDACTED***", res)
    return res

# Startup Assertion Checks
if not SARVAM_API_KEY:
    raise RuntimeError("FATAL BOOT FAILURE: SARVAM_API_KEY environment variable is not set!")

if not RUMIK_API_KEY:
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_API_KEY environment variable is not set!")

if SARVAM_API_KEY.startswith("http://") or SARVAM_API_KEY.startswith("https://") or SARVAM_API_KEY.startswith("wss://"):
    raise RuntimeError("FATAL BOOT FAILURE: SARVAM_API_KEY appears to be a URL string, not an API key!")

if RUMIK_API_KEY.startswith("http://") or RUMIK_API_KEY.startswith("https://") or RUMIK_API_KEY.startswith("wss://"):
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_API_KEY appears to be a URL string, not an API key!")

if not RUMIK_TTS_ENDPOINT.startswith("https://"):
    raise RuntimeError("FATAL BOOT FAILURE: RUMIK_TTS_ENDPOINT must start with https://")

if not (SARVAM_STT_ENDPOINT.startswith("wss://") or SARVAM_STT_ENDPOINT.startswith("https://")):
    raise RuntimeError("FATAL BOOT FAILURE: SARVAM_STT_ENDPOINT must start with wss:// or https://")

# Technical Terms & Common Hinglish Words Devanagari Mapping Dictionary
TECHNICAL_TERMS_MAP = {
    'इंटीग्रेशन': 'integration', 'डिफरेंशियल': 'differential', 'डिफरेंसिएशन': 'differentiation',
    'इक्वेशन': 'equation', 'डेरिवेटिव': 'derivative', 'वेक्टर': 'vector', 'कैपेसिटर': 'capacitor',
    'इलेक्ट्रॉन': 'electron', 'प्रोटॉन': 'proton', 'न्यूट्रॉन': 'neutron', 'न्यूक्लियस': 'nucleus',
    'ऑक्सीडेशन': 'oxidation', 'रिडक्शन': 'reduction', 'इलेक्ट्रोस्टैटिक्स': 'electrostatics',
    'थर्मोडायनामिक्स': 'thermodynamics', 'इक्विलिब्रियम': 'equilibrium', 'हाइब्रिडाइजेशन': 'hybridisation',
    'फ्रीक्वेंसी': 'frequency', 'वेवलेंth': 'wavelength', 'रेजिस्टेंस': 'resistance', 'इंडक्टेंस': 'inductance',
    'कैपेसिटेंस': 'capacitance', 'ग्रेविटेशन': 'gravitation', 'वेलोसिटी': 'velocity', 'एक्सीलरेशन': 'acceleration',
    'मोमेंटम': 'momentum', 'पोटेंशियल': 'potential', 'मैग्नेटिक': 'magnetic', 'फील्ड': 'field',
    'फोटोसिंथेसिस': 'photosynthesis', 'लाइट': 'light', 'रिएक्शन': 'reaction', 'मैकेनिज्म': 'mechanism',
    'डिफरेंस': 'difference', 'करेंट': 'current', 'इलेक्ट्रिसिटी': 'electricity', 'ओहम्स': 'ohms', 'लॉ': 'law',
    'इक्वल': 'equals', 'ऑफ': 'of', 'पावर': 'power', 'लिमिट': 'limit', 'टेंड्स': 'tends', 'टु': 'to', 'जीरो': 'zero',
    'साइन': 'sine', 'बाय': 'by', 'मैट्रिक्स': 'matrix', 'मल्टीप्लिकेशन': 'multiplication', 'रो': 'row', 'इंतु': 'into',
    'कॉलम': 'column', 'बायोलॉजिकल': 'biological', 'क्लासिफिकेशन': 'classification', 'फाइव': 'five', 'किंगडम': 'kingdom',
    'सिस्टम': 'system', 'प्लांट': 'plant', 'एंजियोस्पर्म्स': 'angiosperms', 'जिम्नोस्पर्म्स': 'gymnosperms',
    'ह्यूमन': 'human', 'फिजियोलॉजी': 'physiology', 'डाइजेशन': 'digestion', 'स्टमक': 'stomach',
    'फर्स्ट': 'first', 'डेल्टा': 'delta', 'प्लस': 'plus', 'एटॉमिक': 'atomic', 'स्ट्रक्चर': 'structure',
    'बोहर': 'bohr', 'रेडियस': 'radius', 'केमिकल': 'chemical', 'बॉन्डिंग': 'bonding', 'सॉल्यूशंस': 'solutions',
    'राउल्ट्स': 'raoults', 'वेपर': 'vapor', 'प्रेशर': 'pressure', 'हेलोएल्केन्स': 'haloalkanes',
    'न्यूक्लियोफिलिक': 'nucleophilic', 'सबस्टिट्यूशन': 'substitution', 'प्रोबेबिलिटी': 'probability',
    'यूनियन': 'union', 'डायरेक्शन': 'direction', 'कोसाइन': 'cosines', 'यूनिवर्सल': 'universal', 'फोर्स': 'force',
    'वेव': 'waves', 'डॉपलर': 'doppler', 'इफेक्ट': 'effect', 'शिफ्ट': 'shift', 'कूलम्ब': 'coulomb',
    'हाँ': 'haan', 'है': 'hai', 'कया': 'kya', 'क्या': 'kya', 'कैसे': 'kaise', 'करें': 'karein', 'इसका': 'iska'
}

# Devanagari Unicode Phonetic Mapping Tables
DEV_VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'am', 'अः': 'ah'
}
DEV_MATRAS = {
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h', '्': ''
}
DEV_CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'f', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gy'
}

def transliterate_devanagari_word(word: str) -> str:
    import re
    clean_w = re.sub(r'[^\u0900-\u097F]', '', word)
    if not clean_w:
        return word

    if clean_w in TECHNICAL_TERMS_MAP:
        return TECHNICAL_TERMS_MAP[clean_w]

    res = []
    i = 0
    n = len(clean_w)
    while i < n:
        char = clean_w[i]
        next_char = clean_w[i+1] if i + 1 < n else ""

        if char in DEV_CONSONANTS:
            base = DEV_CONSONANTS[char]
            if next_char in DEV_MATRAS:
                res.append(base + DEV_MATRAS[next_char])
                i += 2
            else:
                if next_char in DEV_CONSONANTS or not next_char:
                    res.append(base + ("a" if i + 1 < n else ""))
                else:
                    res.append(base)
                i += 1
        elif char in DEV_VOWELS:
            res.append(DEV_VOWELS[char])
            i += 1
        elif char in DEV_MATRAS:
            res.append(DEV_MATRAS[char])
            i += 1
        else:
            res.append(char)
            i += 1

    out = "".join(res)
    return out if out else word

def normalize_devanagari_to_roman(text: str) -> str:
    """Normalizes Devanagari script returned by Saaras STT into Romanized Hinglish."""
    import re
    if not text:
        return ""
    words = text.split()
    norm_words = []
    for w in words:
        if re.search(r'[\u0900-\u097F]', w):
            norm_words.append(transliterate_devanagari_word(w))
        else:
            norm_words.append(w)
    return " ".join(norm_words)

# Tier-1 and Tier-2 TTS Safety Filters
TIER1_FORBIDDEN_PATTERNS = [
    r'\\dfrac', r'\\sqrt', r'\\begin', r'\\end', r'\\frac',
    r'\$\$', r'\$', r'\*\*', r'```', r'#{1,6}\s'
]

TIER2_WARNED_PATTERNS = [
    r'[a-zA-Z0-9_]+_[a-zA-Z0-9_]+',  # subscript notation like x_1
    r'[a-zA-Z0-9_]+\^[a-zA-Z0-9_]+'   # superscript notation like x^2
]

def check_tts_safety_filter(text: str) -> Tuple[bool, bool, str]:
    """Returns (tier1_violation, tier2_violation, sanitized_text)."""
    if not text:
        return False, False, ""

    tier1_viol = any(re.search(pat, text) for pat in TIER1_FORBIDDEN_PATTERNS)
    tier2_viol = any(re.search(pat, text) for pat in TIER2_WARNED_PATTERNS)

    clean = text
    clean = re.sub(r'\\(dfrac|sqrt|frac|begin|end)\{[^}]*\}', '', clean)
    clean = re.sub(r'[\$\*\#\`]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()

    return tier1_viol, tier2_viol, clean

def split_into_sentences(text: str) -> List[str]:
    """Splits incoming streaming text into sentence chunks for sentence-by-sentence TTS."""
    if not text:
        return []
    raw = re.split(r'(?<=[.!?|\n])\s+', text)
    return [s.strip() for s in raw if s.strip()]

class SaarasSTTProxy:
    """Proxies Sarvam Saaras v3 STT stream over backend WebSocket connection."""
    def __init__(self, mode: str = "codemix", latency_profile: str = "Fast"):
        self.mode = "codemix"  # Non-negotiable Rule V2
        self.model = "saaras:v3"  # Non-negotiable Rule V1
        self.latency_profile = latency_profile
        self.is_connected = False
        self.active_ws = None

    def close(self):
        """Closes active Sarvam WebSocket connection cleanly."""
        if self.active_ws:
            try:
                asyncio.create_task(self.active_ws.close())
            except Exception:
                pass
            self.active_ws = None
        self.is_connected = False

    async def transcribe_audio_rest(self, pcm_bytes: bytes) -> Tuple[str, str]:
        """Sends accumulated 16kHz PCM audio bytes directly to Sarvam REST STT API."""
        if not pcm_bytes or len(pcm_bytes) < 3200:
            return "", ""

        duration_s = len(pcm_bytes) / 32000.0
        logger.info(f"[SARVAM STT REST REQUEST] Sending {len(pcm_bytes)} PCM bytes ({duration_s:.2f}s audio) to https://api.sarvam.ai/speech-to-text...")

        import io, wave, requests
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm_bytes)
        buf.seek(0)

        headers = {"api-subscription-key": SARVAM_API_KEY}
        files = {'file': ('speech.wav', buf, 'audio/wav')}
        data = {'model': self.model, 'mode': self.mode, 'language_code': 'hi-IN'}

        try:
            loop = asyncio.get_event_loop()
            def _do_rest_call():
                return requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files, timeout=12)

            resp = await loop.run_in_executor(None, _do_rest_call)
            logger.info(f"[SARVAM STT REST HTTP RESPONSE] Status: {resp.status_code}, Body: {resp.text[:300]}")

            if resp.status_code == 200:
                res_data = resp.json()
                raw_transcript = res_data.get("transcript", "")
                norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}'")
                return raw_transcript, norm_transcript
            else:
                logger.error(f"❌ [SARVAM STT REST ERROR] HTTP {resp.status_code}: {resp.text}")
                return "", ""
        except Exception as err:
            logger.error(f"❌ [SARVAM STT REST EXCEPTION] {err}")
            return "", ""

    async def connect_and_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        on_transcript: Callable[[str, str, bool, float], None],
        on_barge_in: Callable[[], None]
    ):
        """Connects to Sarvam Saaras v3 endpoint and streams audio PCM chunks."""
        backoff = 1.0
        max_backoff = 15.0

        headers = {"api-subscription-key": SARVAM_API_KEY}
        endpoint = "wss://api.sarvam.ai/speech-to-text-ws"
        params = f"?model={self.model}&mode={self.mode}&latency={self.latency_profile}"
        uri = f"{endpoint}{params}"

        logger.info(f"[SARVAM STT CONNECTING] Establishing stream to {endpoint} (Headers: {list(headers.keys())})...")

        while True:
            try:
                if SARVAM_API_KEY == "mock-sarvam-key" or "mock" in endpoint:
                    self.is_connected = True
                    async for chunk in audio_stream:
                        if len(chunk) > 0:
                            on_barge_in()
                            await asyncio.sleep(0.01)
                    break

                try:
                    ws_ctx = websockets.connect(uri, additional_headers=headers)
                except TypeError:
                    ws_ctx = websockets.connect(uri, extra_headers=headers)

                async with ws_ctx as ws:
                    self.is_connected = True
                    self.active_ws = ws
                    logger.info(f"✅ [SARVAM STT CONNECTED] Successfully connected to api.sarvam.ai ({self.model}, mode={self.mode})")
                    backoff = 1.0

                    async def send_audio():
                        chunk_count = 0
                        total_bytes = 0
                        async for chunk in audio_stream:
                            if chunk:
                                chunk_count += 1
                                total_bytes += len(chunk)
                                logger.info(f"[SARVAM STT PCM FORWARDED] Chunk #{chunk_count}: {len(chunk)} bytes (Total: {total_bytes} bytes)")
                                await ws.send(chunk)

                    async def receive_transcripts():
                        async for msg in ws:
                            logger.info(f"[SARVAM STT FRAME RECEIVED] {repr(msg[:200])}")
                            data = json.loads(msg)
                            raw_transcript = data.get("transcript", "")
                            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                            is_final = data.get("is_final", False)
                            confidence = data.get("confidence", 0.95)

                            if raw_transcript.strip():
                                logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}', is_final={is_final}")

                            if data.get("speech_onset"):
                                on_barge_in()

                            on_transcript(raw_transcript, norm_transcript, is_final, confidence)

                    await asyncio.gather(send_audio(), receive_transcripts())
                    break

                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, max_backoff)
            except Exception as e:
                self.is_connected = False
                logger.warning(f"⚠️ [SARVAM STT WS CONNECTION FAILURE] {e}. Switching to REST STT audio buffer pipeline...")
                
                # Buffer incoming PCM audio chunks and send to Sarvam REST STT
                pcm_chunks = []
                chunk_count = 0
                total_bytes = 0
                async for chunk in audio_stream:
                    if chunk:
                        chunk_count += 1
                        total_bytes += len(chunk)
                        pcm_chunks.append(chunk)
                        logger.info(f"[SARVAM STT PCM FORWARDED] Chunk #{chunk_count}: {len(chunk)} bytes (Total: {total_bytes} bytes)")

                if pcm_chunks and total_bytes >= 3200:
                    import io, wave, requests
                    all_bytes = b"".join(pcm_chunks)
                    buf = io.BytesIO()
                    with wave.open(buf, 'wb') as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(16000)
                        wf.writeframes(all_bytes)
                    buf.seek(0)

                    files = {'file': ('speech.wav', buf, 'audio/wav')}
                    data = {'model': self.model, 'mode': self.mode, 'language_code': 'hi-IN'}

                    try:
                        loop = asyncio.get_event_loop()
                        def _do_rest_call():
                            return requests.post("https://api.sarvam.ai/speech-to-text", headers=headers, data=data, files=files, timeout=10)
                        
                        resp = await loop.run_in_executor(None, _do_rest_call)
                        if resp.status_code == 200:
                            res_data = resp.json()
                            raw_transcript = res_data.get("transcript", "")
                            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                            logger.info(f"🎯 [SARVAM STT TRANSCRIPT] raw='{raw_transcript}', norm='{norm_transcript}', is_final=True")
                            on_transcript(raw_transcript, norm_transcript, True, 0.98)
                        else:
                            logger.error(f"❌ [SARVAM STT REST ERROR] HTTP {resp.status_code}: {resp.text}")
                    except Exception as rest_err:
                        logger.error(f"❌ [SARVAM STT REST EXCEPTION] {rest_err}")
                break

class RumikTTSProxy:
    """Streaming TTS synthesis via Rumik Silk WebSocket API (voice preset 'Ira', model 'mulberry')."""
    def __init__(self, voice_preset: str = "Ira", model: str = "mulberry"):
        self.voice_preset = voice_preset
        self.model = model

    async def synthesize_text(self, text: str) -> bytes:
        """Connects to Rumik Silk API (https://silk-api.rumik.ai) and returns raw binary PCM audio bytes."""
        import requests

        rumik_key = RUMIK_API_KEY
        if not rumik_key:
            raise RuntimeError("Invalid or missing RUMIK_API_KEY for Rumik Silk TTS synthesis")

        base_url = RUMIK_TTS_ENDPOINT

        def _mint():
            try:
                resp = requests.post(
                    f"{base_url}/v1/tts/ws-connect",
                    headers={"Authorization": f"Bearer {rumik_key}", "Content-Type": "application/json"},
                    json={"model": self.model, "text": text},
                    timeout=10
                )
                if resp.status_code != 200:
                    sanitized_err = sanitize_secret(resp.text)
                    raise RuntimeError(f"Rumik Silk Handshake HTTP {resp.status_code} Error: {sanitized_err}")
                return resp.json()
            except Exception as exc:
                raise RuntimeError(sanitize_secret(str(exc)))

        t0 = time.time()
        loop = asyncio.get_event_loop()
        t_mint_start = time.time()
        handshake_data = await loop.run_in_executor(None, _mint)
        t_mint_end = time.time()
        mint_ms = round((t_mint_end - t_mint_start) * 1000, 2)

        ws_url = handshake_data["ws_url"]
        token = handshake_data["token"]

        pcm_bytes = bytearray()
        t_ws_start = time.time()
        t_first_byte = None

        try:
            async with websockets.connect(f"{ws_url}?token={token}") as ws:
                t_ws_connected = time.time()
                ws_connect_ms = round((t_ws_connected - t_ws_start) * 1000, 2)

                payload = {"text": text, "speaker": self.voice_preset}
                logger.info(f"[RUMIK WS PAYLOAD VERBATIM] url={ws_url}?token={token[:10]}... | payload={json.dumps(payload)}")
                await ws.send(json.dumps(payload))

                while True:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=4.0)
                        if isinstance(msg, bytes):
                            logger.info(f"[RUMIK WS FRAME BINARY] Received binary audio chunk of {len(msg)} bytes")
                            if t_first_byte is None:
                                t_first_byte = time.time()
                            pcm_bytes.extend(msg)
                        elif isinstance(msg, str):
                            logger.info(f"[RUMIK WS FRAME TEXT] Received text frame: {msg}")
                            data = json.loads(msg)
                            msg_type = data.get("type") or data.get("event") or data.get("status")
                            if msg_type in ("done", "complete", "finish", "end"):
                                break
                            elif msg_type == "error":
                                raise RuntimeError(f"Rumik TTS WebSocket Error: {data.get('message') or data}")
                    except asyncio.TimeoutError:
                        logger.warning(f"[RUMIK WS TIMEOUT] ws.recv() timed out after 4.0s for text='{text[:30]}...' (pcm_bytes={len(pcm_bytes)})")
                        break
        except Exception as ws_err:
            raise RuntimeError(sanitize_secret(str(ws_err)))

        t_total = time.time() - t0
        first_byte_ms = round((t_first_byte - t_ws_start) * 1000, 2) if t_first_byte else 0.0

        logger.info(
            f"[RUMIK TTS PER-SENTENCE BREAKDOWN] text='{text[:30]}...' | "
            f"Handshake={mint_ms}ms | WS_Connect={ws_connect_ms}ms | TTFB={first_byte_ms}ms | "
            f"Total={round(t_total, 2)}s | Bytes={len(pcm_bytes)} (~{len(pcm_bytes)/(24000*2):.2f}s audio)"
        )

        if not pcm_bytes:
            raise RuntimeError(f"Rumik Silk returned 0 PCM audio bytes for text: '{text[:40]}...'")

        return bytes(pcm_bytes)

    async def stream_tts(self, text_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
        buffer = ""
        async for chunk in text_stream:
            buffer += chunk
            sentences = split_into_sentences(buffer)
            if len(sentences) > 1:
                for sentence in sentences[:-1]:
                    t1_viol, t2_viol, clean_text = check_tts_safety_filter(sentence)
                    if clean_text:
                        audio_pcm = await self.synthesize_text(clean_text)
                        yield audio_pcm
                buffer = sentences[-1]

        if buffer.strip():
            t1_viol, t2_viol, clean_text = check_tts_safety_filter(buffer)
            if clean_text:
                audio_pcm = await self.synthesize_text(clean_text)
                yield audio_pcm
