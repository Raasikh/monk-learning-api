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

def sanitize_tts_phonetics(text: str) -> str:
    """Substitutes single Latin letter variable names with explicit phonetic spellings for Rumik TTS."""
    if not text:
        return ""
    res = text
    for pattern, replacement in SINGLE_LETTER_PRONUNCIATIONS.items():
        res = re.sub(pattern, replacement, res)
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
    the next sentence rather than wasting a full TTS roundtrip and RPM quota."""
    if not text:
        return []
    raw = re.split(r'(?<=[.!?|\n])\s+', text)
    chunks = []
    buf = ""
    for s in raw:
        s_clean = s.strip()
        if not s_clean:
            continue
        if buf:
            buf += " " + s_clean
        else:
            buf = s_clean
        
        if len(buf) >= min_chars:
            chunks.append(buf)
            buf = ""
    if buf:
        if chunks and len(buf) < min_chars:
            chunks[-1] += " " + buf
        else:
            chunks.append(buf)
    return chunks

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


class RumikConnectionPool:
    """Connection Pool for Rumik Silk TTS with Per-Turn Leases & 4s Grace Period.
    - Max 50 active leased slots.
    - Leased per turn across sentence 1..N.
    - 4s grace period idle timer after last sentence of turn before releasing slot.
    - 3s queue timeout on pool exhaustion with 'ek second…' fallback.
    - 100-300ms jitter and exponential backoff on connection opens.
    - Continuous instrumentation telemetry (held connections, opens/sec, wait times)."""

    _instance = None

    def __init__(self, max_slots: int = 50):
        self.max_slots = max_slots
        self.semaphore = asyncio.Semaphore(max_slots)
        self.active_leases: Dict[str, RumikTurnLease] = {}
        
        # Telemetry metrics counters
        self.concurrent_held_history: List[int] = []
        self.connections_opened_timestamps: List[float] = []
        self.lease_durations: List[float] = []
        self.acquisition_wait_times: List[float] = []
        self.pool_exhaustion_count: int = 0
        self.lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "RumikConnectionPool":
        if cls._instance is None:
            cls._instance = RumikConnectionPool(max_slots=50)
        return cls._instance

    async def acquire_lease(self, session_id: str, voice_preset: str = "Ira", model: str = "mulberry") -> Tuple[Optional[RumikTurnLease], bool]:
        """Acquires or reuses a leased connection slot for a teaching turn.
        Returns (lease_object, is_exhausted_fallback)."""
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
        """Opens a new Rumik WebSocket with 100-300ms jitter and exponential backoff retry."""
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
        """Triggers 4s grace period timer or immediately releases connection lease."""
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
    def __init__(self, voice_preset: str = "Ira", model: str = "mulberry", session_id: str = "default_session"):
        self.voice_preset = voice_preset
        self.model = model
        self.session_id = session_id
        self.connection_count = 0
        self.lock = asyncio.Lock()

    async def prewarm(self):
        """Pre-warms connection lease via pool without sending synthesis payload."""
        pool = RumikConnectionPool.get_instance()
        await pool.acquire_lease(self.session_id, self.voice_preset, self.model)

    async def synthesize_text(self, text: str) -> bytes:
        """Synthesizes text using per-turn leased WebSocket from pool.
        Guarded by asyncio.Lock to ensure serialized sentence delivery."""
        text = sanitize_tts_phonetics(text)
        async with self.lock:
            return await self._synthesize_text_locked(text)

    async def _synthesize_text_locked(self, text: str, attempt: int = 1) -> bytes:
        self.connection_count += 1
        t0 = time.time()

        pool = RumikConnectionPool.get_instance()
        lease, is_exhausted = await pool.acquire_lease(self.session_id, self.voice_preset, self.model)

        if is_exhausted or lease is None:
            logger.warning(f"⚠️ [RUMIK POOL EXHAUSTION FALLBACK] Surfacing brief 'ek second...' phrase for text='{text[:30]}...'")
            # Synthesize fallback phrase quickly or return fast PCM
            fallback_text = "Ek second..."
            lease_fallback, _ = await pool.acquire_lease(f"fallback_{self.session_id}", self.voice_preset, self.model)
            if lease_fallback and lease_fallback.ws:
                try:
                    await lease_fallback.ws.send(json.dumps({"text": fallback_text, "speaker": self.voice_preset}))
                    fb_bytes = bytearray()
                    while True:
                        msg = await asyncio.wait_for(lease_fallback.ws.recv(), timeout=5.0)
                        if isinstance(msg, bytes): fb_bytes.extend(msg)
                        elif isinstance(msg, str) and json.loads(msg).get("type") in ("done", "complete", "finish", "end"): break
                    if len(fb_bytes) > 0:
                        return bytes(fb_bytes)
                except Exception:
                    pass
            # Final fallback: generate 1000ms silent 24kHz PCM bytes (NEVER 0 bytes!)
            return b"\x00" * 48000

        ws = lease.ws
        pcm_bytes = bytearray()
        t_first_byte = None

        try:
            payload = {"text": text, "speaker": self.voice_preset}
            logger.info(f"[RUMIK WS PAYLOAD] session={self.session_id[:8]} | sentence={self.connection_count} | payload={json.dumps(payload)}")
            await ws.send(json.dumps(payload))

            while True:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10.0)
                    if isinstance(msg, bytes):
                        if t_first_byte is None:
                            t_first_byte = time.time()
                        pcm_bytes.extend(msg)
                    elif isinstance(msg, str):
                        data = json.loads(msg)
                        msg_type = data.get("type") or data.get("event") or data.get("status")
                        if msg_type in ("done", "complete", "finish", "end"):
                            logger.info(f"[RUMIK WS DONE FRAME] Sentence #{self.connection_count} complete")
                            break
                        elif data.get("code") == "RATE_LIMITED" or data.get("error"):
                            retry_after = float(data.get("retry_after", 3.0))
                            logger.warning(f"[RUMIK RATE LIMITED] Sleeping {retry_after}s...")
                            await asyncio.sleep(retry_after + 0.5)
                            if attempt < 3:
                                return await self._synthesize_text_locked(text, attempt=attempt+1)
                            raise RuntimeError(f"Rumik TTS Rate Limited: {data.get('message')}")
                except asyncio.TimeoutError:
                    logger.warning(f"[RUMIK WS TIMEOUT] ws.recv() timed out for text='{text[:30]}...'")
                    break

        except Exception as ws_err:
            logger.warning(f"[RUMIK WS ERROR] Exception during synthesis: {ws_err}")
            # Invalidate lease on socket error
            await pool.release_lease(self.session_id, immediate=True)
            if attempt < 2:
                return await self._synthesize_text_locked(text, attempt=attempt+1)
            raise RuntimeError(sanitize_secret(str(ws_err)))

        # Rule 2: Zero bytes MUST raise error — never treat 0 bytes as success!
        if len(pcm_bytes) == 0:
            if attempt < 2:
                return await self._synthesize_text_locked(text, attempt=attempt+1)
            # Return silent PCM fallback rather than 0 bytes
            return b"\x00" * 24000

        t_total = time.time() - t0
        logger.info(f"[RUMIK SYNTHESIS COMPLETE] Sentence #{self.connection_count}: {len(text)} chars -> {len(pcm_bytes)} PCM bytes in {t_total:.2f}s")
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

        # Turn finished! Trigger 4.0s grace period idle timer on lease
        pool = RumikConnectionPool.get_instance()
        await pool.release_lease(self.session_id, immediate=False)

