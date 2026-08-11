import os
import re
import json
import time
import asyncio
import base64
import logging
import requests
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple, Any
import websockets
from app.db import supabase

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

# Single Latin Letter Variable Phonetic Substitutions for Rumik Silk TTS
SINGLE_LETTER_PRONUNCIATIONS = {
    r"\bh\b": "aitch",
    r"\be\b": "ee",
    r"\bv\b": "vee",
    r"\bu\b": "yoo",
    r"\bt\b": "tee",
    r"\bm\b": "em",
    r"\bL\b": "el",
    r"\bT\b": "tee",
    r"\bM\b": "em",
    r"\bg\b": "jee",
    r"\br\b": "ar",
    r"\bs\b": "es"
}

# The prompt forbids LaTeX in speech, but the model still emits plain-notation
# formulas ("H = u² sin²θ / (2g)") — and raw math symbols reach the TTS engine,
# which reads them unpredictably ("=" swallowed, "E" + subscript "k" rendered
# as "eek"). Spell them out before synthesis. Ordered: multi-char first.
MATH_SYMBOL_PRONUNCIATIONS = [
    (r"\s*≈\s*", " approximately "),
    (r"\s*±\s*", " plus or minus "),
    (r"\s*=\s*", " equals "),
    (r"\s*×\s*", " times "),
    (r"\s+/\s+", " over "),
    (r"\^2\b", " squared"),
    (r"\^3\b", " cubed"),
    (r"²", " squared"),
    (r"³", " cubed"),
    (r"√\s*", " root "),
    (r"θ", " theta"),
    (r"π", " pi"),
    (r"Δ", " delta "),
    (r"μ", " mu"),
    (r"λ", " lambda"),
    (r"ω", " omega"),
    (r"α", " alpha"),
    (r"β", " beta"),
    (r"°", " degrees"),
    # Subscripts: "a_x" / "E_k" → "a x" / "E k" so the letters are spoken
    # separately instead of fused into a nonsense word.
    (r"(\w)_(\w)", r"\1 \2"),
]

def sanitize_tts_phonetics(text: str) -> str:
    """Substitutes math symbols and single Latin letter variable names with explicit phonetic spellings for Rumik TTS."""
    if not text:
        return ""
    res = text
    for pattern, replacement in MATH_SYMBOL_PRONUNCIATIONS:
        res = re.sub(pattern, replacement, res)
    for pattern, replacement in SINGLE_LETTER_PRONUNCIATIONS.items():
        res = re.sub(pattern, replacement, res)
    return re.sub(r"\s{2,}", " ", res).strip()

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
    'हाँ': 'haan', 'है': 'hai', 'हैं': 'hain', 'कया': 'kya', 'क्या': 'kya', 'कैसे': 'kaise', 'करें': 'karein', 'इसका': 'iska',
    'भाई': 'bhai', 'नेक्स्ट': 'next', 'टॉपिक': 'topic', 'कांसेप्ट': 'concept', 'कंटिन्यू': 'continue', 'डाउट': 'doubt',
    'क्लियर': 'clear', 'चलो': 'chalo', 'आगे': 'aage', 'बढ़ो': 'badho', 'समझ': 'samajh', 'बताओ': 'batao', 'फिर': 'fir',
    'लोग': 'log', 'हम': 'ham', 'उत्तर': 'answer', 'प्रश्न': 'question', 'डिफरेंशियल': 'differential', 'प्रेशर': 'pressure',
    'इक्वेशन': 'equation'
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

def split_into_sentences(text: str, min_chars: int = 100) -> List[str]:
    """Splits incoming streaming text into sentence chunks for sentence-by-sentence TTS.
    Batches short leading fragments (<100 chars) together so short phrases join
    the next sentence rather than wasting a full TTS roundtrip and RPM quota.

    A question is the one thing that is never batched. The client mounts the
    answer chips against the chunk carrying the question, so gluing the
    checkpoint question onto the statement before it (the batching rule did
    exactly that: "...free fall under g. Now, here's a quick check: ...?"
    arrived as ONE 226-char chunk) put the question on screen 14 seconds before
    it was spoken and left the chips with no sentence of their own to fire on.
    One extra TTS roundtrip per turn is the price; rumik_requests already
    accounts for the trailing question chunk separately."""
    if not text:
        return []
    raw = re.split(r'(?<=[.!?|\n])\s+', text)
    chunks = []
    buf = ""
    for s in raw:
        s_clean = s.strip()
        if not s_clean:
            continue
        if s_clean.endswith("?"):
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(s_clean)
            continue
        if buf:
            buf += " " + s_clean
        else:
            buf = s_clean

        if len(buf) >= min_chars:
            chunks.append(buf)
            buf = ""
    if buf:
        if chunks and len(buf) < min_chars and not chunks[-1].endswith("?"):
            chunks[-1] += " " + buf
        else:
            chunks.append(buf)
    return chunks

class SaarasSTTProxy:
    """Proxies Sarvam Saaras v3 STT stream over backend WebSocket connection."""
    def __init__(self, mode: str = "codemix", latency_profile: str = "Fast", language: str = "hinglish"):
        self.mode = "codemix"  # Non-negotiable Rule V2
        self.model = "saaras:v3"  # Non-negotiable Rule V1
        self.latency_profile = latency_profile
        # language_code was hardcoded to hi-IN for every session, so a student
        # speaking English in an English session got their answer transcribed
        # into Devanagari Hindi — the tutor then graded a transliteration of
        # what they never said. Hinglish keeps hi-IN (codemix handles the mix);
        # English sessions transcribe as Indian English.
        self.language_code = "en-IN" if language == "english" else "hi-IN"
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
        data = {'model': self.model, 'mode': self.mode, 'language_code': self.language_code}

        try:
            loop = asyncio.get_event_loop()
            def _do_rest_call():
                record_stt_request()
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
                    data = {'model': self.model, 'mode': self.mode, 'language_code': self.language_code}

                    try:
                        loop = asyncio.get_event_loop()
                        def _do_rest_call():
                            record_stt_request()
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

class RumikTurnLease:
    """Turn-scoped lease wrapping an active Rumik Silk WebSocket connection."""
    def __init__(self, pool: "RumikConnectionPool", session_id: str, ws: websockets.WebSocketClientProtocol, voice_preset: str, model: str):
        self.pool = pool
        self.session_id = session_id
        self.ws = ws
        self.voice_preset = voice_preset
        self.model = model
        self.start_time = time.time()
        self.idle_task: Optional[asyncio.Task] = None

    def cancel_idle_timer(self):
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            self.idle_task = None

    def start_idle_timer(self, delay_seconds: float = 4.0):
        self.cancel_idle_timer()
        self.idle_task = asyncio.create_task(self._idle_timer_coro(delay_seconds))

    async def _idle_timer_coro(self, delay_seconds: float):
        try:
            await asyncio.sleep(delay_seconds)
            logger.info(f"⏳ [RUMIK 4S GRACE EXPIRED] 4.0s idle timer expired for session '{self.session_id[:8]}'. Closing socket...")
            await self.pool._close_and_remove_lease(self.session_id)
        except asyncio.CancelledError:
            pass

    def get_lease_duration(self) -> float:
        return time.time() - self.start_time


# Filler phrases must follow the SESSION LANGUAGE. These played as hardcoded
# Hinglish in English sessions — an English-speaking student suddenly heard
# "Ek second, soch rahi hoon…" mid-lesson.
#
# Keyed (gender, language). Only Ira and Lucas are prewarmed because those are
# the only two presets a persona ever maps to, so the boot cost is unchanged.
# Pool key the boot-time filler prewarm leases under. Distinct from any real
# session id so live-session accounting can tell the two apart.
PREWARM_SESSION_KEY = "boot_prewarm"

# Sarvam STT calls, for the platform metrics sampler. The sampler used to
# report the count of DB rows in phase='teaching' as its "Sarvam requests",
# which measured nothing of the sort.
_STT_REQUEST_TIMESTAMPS: List[float] = []


def record_stt_request():
    _STT_REQUEST_TIMESTAMPS.append(time.time())


def stt_requests_last_60s() -> int:
    cutoff = time.time() - 60.0
    recent = [t for t in _STT_REQUEST_TIMESTAMPS if t >= cutoff]
    if len(_STT_REQUEST_TIMESTAMPS) > 5000:
        _STT_REQUEST_TIMESTAMPS[:] = recent
    return len(recent)

# No trailing ellipses and no leading "Hmm" — measured, Rumik renders both as
# long drawn-out pauses ("Hmm, ek minute…" came back 4.6s for 15 characters,
# four times its natural length), which is exactly the dragged, stretched
# delivery these clips were criticised for. Plain short sentences instead.
FILLER_PHRASES = {
    ("female", "hinglish"): [
        "Ek second, soch rahi hoon.",
        "Ruko zara, main dekh rahi hoon.",
        "Ek minute.",
    ],
    ("male", "hinglish"): [
        "Ek second, soch raha hoon.",
        "Ruko zara, main dekh raha hoon.",
        "Ek minute.",
    ],
    ("female", "english"): [
        "One moment, let me think.",
        "Just a second.",
        "Give me a moment.",
    ],
    ("male", "english"): [
        "One moment, let me think.",
        "Just a second.",
        "Give me a moment.",
    ],
}

PRESET_GENDER = {"Ira": "female", "Veda": "female", "Lucas": "male", "Drona": "male"}


def filler_cache_key(voice_preset: str, language: str) -> str:
    return f"{voice_preset}:{(language or 'hinglish').lower()}"

class FillerAudioCache:
    """Pre-synthesizes filler audio phrases at startup and caches raw PCM bytes in memory.
    Zero runtime synthesis requests for filler audio."""
    _instance = None
    _lock = asyncio.Lock()

    def __init__(self):
        self.cache: Dict[str, List[bytes]] = {}
        self.is_prewarmed = False
        self._synth_in_flight: set = set()

    @classmethod
    def get_instance(cls) -> "FillerAudioCache":
        if cls._instance is None:
            cls._instance = FillerAudioCache()
        return cls._instance

    def _live_lease_count(self) -> int:
        """Student sessions currently holding a Rumik connection."""
        pool = RumikConnectionPool.get_instance()
        return sum(1 for sid in list(pool.active_leases) if sid != PREWARM_SESSION_KEY)

    async def _wait_for_idle_pool(self, max_wait_s: float = 900.0) -> bool:
        """Blocks until no student session holds a connection."""
        t0 = time.time()
        announced = False
        while time.time() - t0 < max_wait_s:
            if self._live_lease_count() == 0:
                return True
            if not announced:
                logger.info("⏸️ [FILLER PREWARM DEFERRED] A live session is using the pool — waiting for it to finish.")
                announced = True
            await asyncio.sleep(2.0)
        return False

    async def prewarm_all(self, presets: Tuple[str, ...] = ("Ira", "Lucas"),
                          languages: Tuple[str, ...] = ("hinglish", "english")):
        """Synthesizes filler phrases for the given voices/languages.

        No longer runs at boot — see app/main.py. Called lazily by
        ensure_cached() the first time a filler is actually wanted, and by
        then usually for ONE voice and ONE language rather than all four
        combinations.

        Two rules, both learned from a live session sharing a container with a
        fresh deploy's prewarm:

        1. ONE connection for all phrases. This used to open and close a
           connection per phrase — 12 opens against Rumik's rate budget, and
           the churn showed up as a second concurrent slot right through a
           student's turn.
        2. Never run while a student is being taught. A live class always gets
           the pool to itself, so one session means exactly one connection.
        """
        if not await self._wait_for_idle_pool():
            logger.warning("⚠️ [FILLER SYNTH SKIPPED] Pool stayed busy with live sessions; fillers stay uncached.")
            return

        t_start = time.time()
        jobs: List[Tuple[str, str, str]] = []
        for preset in presets:
            gender = PRESET_GENDER[preset]
            for lang in languages:
                key = filler_cache_key(preset, lang)
                if self.cache.get(key):
                    continue  # already have this voice/language
                self.cache.setdefault(key, [])
                for phrase in FILLER_PHRASES[(gender, lang)]:
                    jobs.append((key, preset, phrase))
        if not jobs:
            return

        pool = RumikConnectionPool.get_instance()
        synthesized = 0
        try:
            for key, preset, phrase in jobs:
                # A student who arrives mid-synthesis takes priority: hand the
                # connection back, wait them out, then pick up where we left off.
                if self._live_lease_count() > 0:
                    await pool.release_lease(PREWARM_SESSION_KEY, immediate=True)
                    if not await self._wait_for_idle_pool():
                        break

                lease, is_exhausted = await pool.acquire_lease(PREWARM_SESSION_KEY, preset, "mulberry")
                if is_exhausted or lease is None or not lease.ws:
                    logger.warning("⚠️ [FILLER SYNTH WARN] No connection available; stopping.")
                    break
                pcm = await self._synthesize_on_ws(lease.ws, phrase, preset)
                if pcm:
                    self.cache[key].append(pcm)
                    synthesized += 1
        finally:
            try:
                await pool.release_lease(PREWARM_SESSION_KEY, immediate=True)
            except Exception:
                pass

        if synthesized:
            self.is_prewarmed = True
        elapsed = time.time() - t_start
        logger.info(
            f"✅ [FILLER CACHED] {synthesized}/{len(jobs)} phrases synthesized "
            f"in {elapsed:.1f}s (1 connection, lazy)"
        )

    def ensure_cached(self, voice_preset: str, language: str):
        """Kicks off background synthesis for this voice/language if missing.

        Fire-and-forget by design: the caller needing a filler RIGHT NOW is
        usually mid-rate-limit, when synthesizing is exactly what we cannot
        do. That first occurrence degrades to a brief silence; this makes
        sure the next one has a real phrase.
        """
        key = filler_cache_key(voice_preset, language)
        if self.cache.get(key) or key in self._synth_in_flight:
            return
        self._synth_in_flight.add(key)

        async def _run():
            try:
                await self.prewarm_all(presets=(voice_preset,), languages=(language,))
            except Exception as err:
                logger.warning(f"Lazy filler synthesis failed for {key}: {err}")
            finally:
                self._synth_in_flight.discard(key)

        try:
            asyncio.create_task(_run())
        except RuntimeError:
            self._synth_in_flight.discard(key)

    async def _synthesize_on_ws(self, ws, text: str, voice_preset: str) -> bytes:
        """Synthesizes one phrase over an already-open connection.

        Returns b"" on failure — an uncached filler is simply absent, never a
        block of silence pretending to be speech.
        """
        try:
            await ws.send(json.dumps({"text": text, "speaker": voice_preset}))
            buf = bytearray()
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=6.0)
                if isinstance(msg, bytes):
                    buf.extend(msg)
                elif isinstance(msg, str):
                    d = json.loads(msg)
                    if d.get("type") in ("done", "complete", "finish", "end"):
                        break
                    if d.get("code") == "RATE_LIMITED" or d.get("error"):
                        logger.warning(f"⚠️ [FILLER PREWARM WARN] Rumik refused '{text[:24]}…': {d.get('message') or d.get('code')}")
                        return b""
            return bytes(buf)
        except Exception as e:
            logger.warning(f"⚠️ [FILLER PREWARM WARN] Could not pre-synthesize '{text[:24]}…' for '{voice_preset}': {e}")
            return b""

    def has_cached_fillers(self, voice_preset: str, language: str = "hinglish") -> bool:
        """Whether a REAL filler exists for this voice/language.

        get_random_filler() falls back to two seconds of silence so a
        rate-limit gap is never dead air. That is wrong for the answer
        acknowledgment, where silence would just delay the real reply — those
        callers check here first.
        """
        if self.cache.get(filler_cache_key(voice_preset, language)):
            return True
        fallback_preset = "Lucas" if PRESET_GENDER.get(voice_preset) == "male" else "Ira"
        return bool(
            self.cache.get(filler_cache_key(fallback_preset, language))
            or self.cache.get(filler_cache_key(fallback_preset, "hinglish"))
        )

    def get_random_filler(self, voice_preset: str, language: str = "hinglish",
                          exclude_idx: Optional[int] = None) -> Tuple[int, bytes]:
        """Returns (index, pcm_bytes) of a cached filler for this voice AND language."""
        import random
        phrases_pcm = self.cache.get(filler_cache_key(voice_preset, language))
        if not phrases_pcm:
            fallback_preset = "Lucas" if PRESET_GENDER.get(voice_preset) == "male" else "Ira"
            phrases_pcm = (self.cache.get(filler_cache_key(fallback_preset, language))
                           or self.cache.get(filler_cache_key(fallback_preset, "hinglish")))

        if not phrases_pcm:
            # Nothing cached yet (fillers are synthesized lazily now). Cover
            # this gap with silence and get the clips made for next time.
            self.ensure_cached(voice_preset, language)
            return 0, b"\x00" * 48000

        indices = [i for i in range(len(phrases_pcm)) if i != exclude_idx]
        if not indices:
            indices = list(range(len(phrases_pcm)))

        chosen_idx = random.choice(indices)
        return chosen_idx, phrases_pcm[chosen_idx]


class RumikConnectionPool:
    """Connection Pool for Rumik Silk TTS with Per-Turn Leases & 4s Grace Period."""
    _instance = None

    def __init__(self, max_slots: int = 50):
        self.max_slots = max_slots
        self.semaphore = asyncio.Semaphore(max_slots)
        self.active_leases: Dict[str, RumikTurnLease] = {}
        
        self.concurrent_held_history: List[int] = []
        self.connections_opened_timestamps: List[float] = []
        # Two different things can count against Rumik's 100 RPM: opening a
        # connection (one POST to /v1/tts/ws-connect) and sending text down an
        # already-open socket. We do not know which one Rumik meters, and they
        # differ by roughly 6x per turn, so track both and plan against the
        # larger. See get_rate_usage().
        self.synthesis_requests_timestamps: List[float] = []
        self.lease_durations: List[float] = []
        self.acquisition_wait_times: List[float] = []
        self.pool_exhaustion_count: int = 0
        self.lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "RumikConnectionPool":
        if cls._instance is None:
            cls._instance = RumikConnectionPool(max_slots=50)
        return cls._instance

    def record_synthesis_request(self):
        """One text frame sent down an open socket. Counted separately from opens."""
        self.synthesis_requests_timestamps.append(time.time())

    def get_rate_usage(self) -> Tuple[int, int]:
        """Returns (connection_opens, synthesis_sends) in the trailing 60s."""
        cutoff = time.time() - 60.0
        opens = sum(1 for ts in self.connections_opened_timestamps if ts >= cutoff)
        sends = sum(1 for ts in self.synthesis_requests_timestamps if ts >= cutoff)
        # Keep the windows from growing without bound over a long-lived process.
        if len(self.connections_opened_timestamps) > 5000:
            self.connections_opened_timestamps = [t for t in self.connections_opened_timestamps if t >= cutoff]
        if len(self.synthesis_requests_timestamps) > 5000:
            self.synthesis_requests_timestamps = [t for t in self.synthesis_requests_timestamps if t >= cutoff]
        return opens, sends

    def get_requests_in_last_60s(self) -> int:
        """Worst-case RPM against Rumik's 100/min cap.

        Deliberately the max of the two counters rather than opens alone: if
        Rumik meters text frames we would otherwise under-report by ~6x and
        only find out via RATE_LIMITED frames.
        """
        opens, sends = self.get_rate_usage()
        return max(opens, sends)

    async def acquire_lease(self, session_id: str, voice_preset: str = "Ira", model: str = "mulberry") -> Tuple[Optional[RumikTurnLease], bool]:
        t0 = time.time()
        
        async with self.lock:
            if session_id in self.active_leases:
                lease = self.active_leases[session_id]
                lease.cancel_idle_timer()
                logger.info(f"🔄 [RUMIK POOL REUSE] Reusing connection lease for session '{session_id[:8]}'")
                return lease, False

        acquired = False
        try:
            await asyncio.wait_for(self.semaphore.acquire(), timeout=3.0)
            acquired = True
        except asyncio.TimeoutError:
            async with self.lock:
                self.pool_exhaustion_count += 1
                concurrent_now = self.max_slots - self.semaphore._value
                logger.error(f"❌ [RUMIK POOL EXHAUSTION] Timeout 3.0s waiting for connection slot! Active concurrent slots: {concurrent_now}/{self.max_slots}")
            return None, True

        wait_ms = round((time.time() - t0) * 1000, 2)
        async with self.lock:
            self.acquisition_wait_times.append(wait_ms)
            self.connections_opened_timestamps.append(time.time())

        ws = await self._open_connection_with_jitter(voice_preset, model)
        if ws is None:
            self.semaphore.release()
            return None, True

        lease = RumikTurnLease(
            pool=self,
            session_id=session_id,
            ws=ws,
            voice_preset=voice_preset,
            model=model
        )

        async with self.lock:
            self.active_leases[session_id] = lease
            concurrent_now = len(self.active_leases)
            self.concurrent_held_history.append(concurrent_now)
            logger.info(f"🔑 [RUMIK POOL ACQUIRE] Lease acquired for session '{session_id[:8]}'. Wait={wait_ms}ms | Concurrent slots: {concurrent_now}/{self.max_slots}")

        return lease, False

    async def _open_connection_with_jitter(self, voice_preset: str, model: str) -> Optional[websockets.WebSocketClientProtocol]:
        import random, requests
        jitter = random.uniform(0.1, 0.3)
        await asyncio.sleep(jitter)

        rumik_key = RUMIK_API_KEY
        if not rumik_key:
            return None

        base_url = RUMIK_TTS_ENDPOINT
        backoff = 0.5

        for attempt in range(1, 4):
            try:
                def _mint():
                    return requests.post(
                        f"{base_url}/v1/tts/ws-connect",
                        headers={"Authorization": f"Bearer {rumik_key}", "Content-Type": "application/json"},
                        json={"model": model, "text": "Init"},
                        timeout=8
                    ).json()

                loop = asyncio.get_event_loop()
                handshake = await loop.run_in_executor(None, _mint)
                ws_url = handshake.get("ws_url")
                token = handshake.get("token")
                if ws_url and token:
                    ws = await websockets.connect(
                        f"{ws_url}?token={token}",
                        ping_interval=None,
                        close_timeout=5.0
                    )
                    return ws
            except Exception as err:
                logger.warning(f"⚠️ [RUMIK CONNECT RETRY #{attempt}] {err}. Sleeping {backoff}s...")
                await asyncio.sleep(backoff)
                backoff *= 2.0

        return None

    async def release_lease(self, session_id: str, immediate: bool = False):
        async with self.lock:
            if session_id not in self.active_leases:
                return
            lease = self.active_leases[session_id]

        if immediate:
            await self._close_and_remove_lease(session_id)
        else:
            lease.start_idle_timer(4.0)

    async def _close_and_remove_lease(self, session_id: str):
        async with self.lock:
            if session_id in self.active_leases:
                lease = self.active_leases.pop(session_id)
                dur = lease.get_lease_duration()
                self.lease_durations.append(dur)
                try:
                    await lease.ws.close()
                except Exception:
                    pass
                self.semaphore.release()
                concurrent_now = len(self.active_leases)
                logger.info(f"🔓 [RUMIK POOL RELEASE] Released lease for session '{session_id[:8]}' after {dur:.2f}s. Concurrent slots: {concurrent_now}/{self.max_slots}")


class RumikTTSProxy:
    """Streaming TTS synthesis via Rumik Silk WebSocket API using Per-Turn Connection Pool."""
    def __init__(self, voice_preset: str = "Ira", model: str = "mulberry", session_id: str = "default_session",
                 language: str = "hinglish", pool_key: Optional[str] = None):
        self.voice_preset = voice_preset
        self.language = language
        self.model = model
        self.session_id = session_id
        # Pool leases are keyed separately from the DB session id. Two
        # connections can briefly exist for ONE session (a refresh or resume
        # taking over), and with a shared key the retiring connection's
        # release closed the very socket the new one was synthesizing on —
        # "sent 1000 (OK); then received 1000 (OK)" mid-sentence. session_id
        # stays the DB identity (rate_limit_hits writes use it).
        self.pool_key = pool_key or session_id
        self.connection_count = 0
        self.lock = asyncio.Lock()

    async def prewarm(self):
        pool = RumikConnectionPool.get_instance()
        await pool.acquire_lease(self.pool_key, self.voice_preset, self.model)

    async def end_turn(self, next_turn_is_immediate: bool = False):
        """Hand the slot back once a turn's last sentence has been synthesized.

        Sentences *within* a turn already reuse the lease, so at a turn boundary
        the grace period only pays for itself if another turn is about to start
        right now — i.e. an auto-advanced teaching turn, whose prewarm() lands
        within a second or two and reuses the socket instead of re-handshaking.

        When the turn ends on a checkpoint the student is about to spend 20-60s
        reading and answering. Holding the slot through that is pure waste, so
        release immediately and let someone else have it.
        """
        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=not next_turn_is_immediate)

    async def abandon(self):
        """Drop the slot immediately — student disconnected, nothing to reuse."""
        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=True)

    async def synthesize_text(
        self,
        text: str,
        on_filler_cb: Optional[Any] = None,
        segment_index: int = 1,
        on_audio_part: Optional[Any] = None,
    ) -> bytes:
        """Synthesizes text using per-turn leased WebSocket from pool with zero-gap rate-limit fillers.

        With `on_audio_part`, PCM is flushed to the callback in ~1s batches AS
        RUMIK SYNTHESIZES instead of buffered until the sentence is done —
        the student hears the first second of a sentence while the rest is
        still being generated. When anything was emitted through the callback
        the return value is b"" so the caller doesn't send the audio twice.
        """
        text = sanitize_tts_phonetics(text)
        async with self.lock:
            return await self._synthesize_text_locked(
                text, attempt=1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                on_audio_part=on_audio_part,
            )

    def _record_rate_limit_hit_async(self):
        """Asynchronously increments rate_limit_hits in drona_sessions."""
        try:
            async def _update():
                s_res = supabase.table("drona_sessions").select("rate_limit_hits").eq("id", self.session_id).execute()
                current_hits = 0
                if s_res.data and len(s_res.data) > 0 and s_res.data[0].get("rate_limit_hits") is not None:
                    current_hits = s_res.data[0]["rate_limit_hits"]
                supabase.table("drona_sessions").update({
                    "rate_limit_hits": current_hits + 1
                }).eq("id", self.session_id).execute()
            asyncio.create_task(_update())
        except Exception as e:
            logger.warning(f"Failed to record rate limit hit in drona_sessions: {e}")

    async def _synthesize_text_locked(
        self,
        text: str,
        attempt: int = 1,
        on_filler_cb: Optional[Any] = None,
        segment_index: int = 1,
        on_audio_part: Optional[Any] = None,
    ) -> bytes:
        self.connection_count += 1
        t0 = time.time()

        pool = RumikConnectionPool.get_instance()
        lease, is_exhausted = await pool.acquire_lease(self.pool_key, self.voice_preset, self.model)

        if is_exhausted or lease is None:
            logger.warning(f"⚠️ [RUMIK POOL EXHAUSTION FALLBACK] Surfacing cached filler phrase for text='{text[:30]}...'")
            filler_cache = FillerAudioCache.get_instance()
            _, filler_pcm = filler_cache.get_random_filler(self.voice_preset, self.language)
            if on_filler_cb:
                try:
                    await on_filler_cb(filler_pcm)
                except Exception:
                    pass
            return filler_pcm

        ws = lease.ws
        pcm_bytes = bytearray()
        t_first_byte = None

        # Progressive flush state. ~1s of 24kHz 16-bit mono per part: small
        # enough that the first part reaches the student seconds before the
        # sentence finishes synthesizing, big enough not to spam frames.
        PART_BYTES = 48000
        part_buf = bytearray()
        emitted_parts = 0

        async def _flush_part(force: bool = False):
            nonlocal emitted_parts
            if on_audio_part is None:
                return
            if len(part_buf) >= PART_BYTES or (force and part_buf):
                chunk = bytes(part_buf)
                part_buf.clear()
                emitted_parts += 1
                if emitted_parts == 1:
                    logger.info(f"⚡ [RUMIK FIRST PART] Sentence #{self.connection_count}: first {len(chunk)} bytes flushed {time.time() - t0:.2f}s in (sentence still synthesizing)")
                try:
                    await on_audio_part(chunk)
                except Exception as part_err:
                    logger.warning(f"on_audio_part callback failed: {part_err}")

        try:
            payload = {"text": text, "speaker": self.voice_preset}
            logger.info(f"[RUMIK WS PAYLOAD] session={self.session_id[:8]} | sentence={self.connection_count} | payload={json.dumps(payload)}")
            pool.record_synthesis_request()
            await ws.send(json.dumps(payload))

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    if isinstance(msg, bytes):
                        if t_first_byte is None:
                            t_first_byte = time.time()
                        pcm_bytes.extend(msg)
                        if on_audio_part is not None:
                            part_buf.extend(msg)
                            await _flush_part()
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        msg_type = data.get("type") or data.get("event") or data.get("status")
                        if msg_type in ("done", "complete", "finish", "end"):
                            logger.info(f"[RUMIK WS DONE FRAME] Sentence #{self.connection_count} complete")
                            await _flush_part(force=True)
                            break
                        elif data.get("code") == "RATE_LIMITED" or data.get("error"):
                            if emitted_parts > 0:
                                # Part of this sentence has already PLAYED —
                                # retrying would speak its opening twice. Keep
                                # what was delivered and move on.
                                logger.warning(f"🚨 [RUMIK ERROR MID-STREAM] Sentence #{self.connection_count} errored after {emitted_parts} parts played — not retrying to avoid double speech.")
                                await pool.release_lease(self.pool_key, immediate=True)
                                return b""
                            retry_after = float(data.get("retry_after", 5.0))
                            opens_60s, sends_60s = pool.get_rate_usage()

                            logger.warning(
                                f"🚨 [RUMIK RATE LIMITED] session={self.session_id} | seg={segment_index} | "
                                f"retry_after={retry_after}s | opens_last_60s={opens_60s} | "
                                f"sends_last_60s={sends_60s} | open_leases={len(pool.active_leases)}/{pool.max_slots} | "
                                f"attempt={attempt}/3"
                            )

                            self._record_rate_limit_hit_async()
                            filler_cache = FillerAudioCache.get_instance()

                            # 1. Play first cached filler immediately (0 requests, no gap!)
                            idx1, filler1_pcm = filler_cache.get_random_filler(self.voice_preset, self.language)
                            if on_filler_cb:
                                try:
                                    await on_filler_cb(filler1_pcm)
                                except Exception:
                                    pass

                            # 2. Smart mid-wait filler: if retry_after > 15s, play second filler mid-way
                            if retry_after > 15.0:
                                await asyncio.sleep(10.0)
                                idx2, filler2_pcm = filler_cache.get_random_filler(self.voice_preset, self.language, exclude_idx=idx1)
                                logger.info(f"⏳ [RUMIK MID-WAIT FILLER] Playing 2nd filler for session {self.session_id[:8]} (retry_after={retry_after}s)")
                                if on_filler_cb:
                                    try:
                                        await on_filler_cb(filler2_pcm)
                                    except Exception:
                                        pass
                                await asyncio.sleep(max(0.1, retry_after - 10.0 + 0.5))
                            else:
                                await asyncio.sleep(retry_after + 0.5)

                            # 3. Retry synthesis (up to 3 attempts)
                            if attempt < 3:
                                await pool.release_lease(self.pool_key, immediate=True)
                                return await self._synthesize_text_locked(
                                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                                    on_audio_part=on_audio_part,
                                )

                            raise RuntimeError(f"Rumik TTS Rate Limited (Attempt {attempt}/3): {data.get('message') or 'Rate limit exceeded'}")
                except asyncio.TimeoutError:
                    logger.warning(f"[RUMIK WS TIMEOUT] ws.recv() timed out for text='{text[:30]}...'")
                    break

        except Exception as ws_err:
            logger.warning(f"[RUMIK WS ERROR] Exception during synthesis: {ws_err}")
            await pool.release_lease(self.pool_key, immediate=True)
            if emitted_parts > 0:
                # Same double-speech guard as the rate-limit path.
                logger.warning(f"[RUMIK WS ERROR MID-STREAM] Sentence #{self.connection_count} died after {emitted_parts} parts played — not retrying.")
                return b""
            if attempt < 3:
                return await self._synthesize_text_locked(
                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                    on_audio_part=on_audio_part,
                )
            raise RuntimeError(sanitize_secret(str(ws_err)))

        if len(pcm_bytes) == 0:
            if attempt < 3:
                return await self._synthesize_text_locked(
                    text, attempt=attempt + 1, on_filler_cb=on_filler_cb, segment_index=segment_index,
                    on_audio_part=on_audio_part,
                )
            return b"\x00" * 24000

        t_total = time.time() - t0
        logger.info(f"[RUMIK SYNTHESIS COMPLETE] Sentence #{self.connection_count}: {len(text)} chars -> {len(pcm_bytes)} PCM bytes in {t_total:.2f}s")
        if emitted_parts > 0:
            # Everything already went out through on_audio_part.
            return b""
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

        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.pool_key, immediate=False)


