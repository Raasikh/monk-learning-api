import os
import re
import json
import asyncio
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple
import websockets

# Configuration constants
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_STT_ENDPOINT = os.getenv("SARVAM_STT_ENDPOINT", "")
RUMIK_TTS_ENDPOINT = os.getenv("RUMIK_TTS_ENDPOINT", "")
RUMIK_API_KEY = os.getenv("RUMIK_API_KEY", "")

# Devanagari to Romanized Hinglish Mapping Dictionary for STT Normalization (§3)
DEVANAGARI_ROMAN_MAP = {
    'इसका': 'iska', 'इंटीग्रेशन': 'integration', 'कैसे': 'kaise', 'करें': 'karein',
    'वेक्टर': 'vector', 'रेजोल्यूशन': 'resolution', 'फार्मूला': 'formula', 'क्या': 'kya', 'है': 'hai',
    'फोटोसिंथेसिस': 'photosynthesis', 'लाइट': 'light', 'रिएक्शन': 'reaction', 'मैकेनिज्म': 'mechanism',
    'डिफरेंस': 'difference', 'करेंट': 'current', 'इलेक्ट्रिसिटी': 'electricity', 'ओहम्स': 'ohms',
    'लॉ': 'law', 'इक्वल': 'equals', 'डेरिवेटिव': 'derivative', 'ऑफ': 'of', 'पावर': 'power',
    'लिमिट': 'limit', 'टेंड्स': 'tends', 'टु': 'to', 'जीरो': 'zero', 'साइन': 'sine', 'बाय': 'by',
    'मैट्रिक्स': 'matrix', 'मल्टीप्लिकेशन': 'multiplication', 'रो': 'row', 'इंतु': 'into', 'कॉलम': 'column',
    'बायोलॉजिकल': 'biological', 'क्लासिफिकेशन': 'classification', 'फाइव': 'five', 'किंगडम': 'kingdom', 'सिस्टम': 'system',
    'प्लांट': 'plant', 'एंजियोस्पर्म्स': 'angiosperms', 'जिम्नोस्पर्म्स': 'gymnosperms',
    'ह्यूमन': 'human', 'फिजियोलॉजी': 'physiology', 'डाइजेशन': 'digestion', 'स्टमक': 'stomach',
    'थर्मोडायनामिक्स': 'thermodynamics', 'फर्स्ट': 'first', 'डेल्टा': 'delta', 'प्लस': 'plus',
    'एटॉमिक': 'atomic', 'स्ट्रक्चर': 'structure', 'बोहर': 'bohr', 'रेडियस': 'radius',
    'केमिकल': 'chemical', 'बॉन्डिंग': 'bonding', 'हाइब्रिडाइजेशन': 'hybridisation',
    'इक्विलिब्रियम': 'equilibrium', 'डिफरेंसिएशन': 'differentiation', 'वेलोसिटी': 'velocity', 'ऑक्सीडेशन': 'oxidation',
    'रेडिएशन': 'radiation', 'न्यूक्लियस': 'nucleus', 'इलेक्ट्रॉन': 'electron', 'प्रोटॉन': 'proton', 'न्यूट्रॉन': 'neutron',
    'कैपेसिटेंस': 'capacitance', 'इंडक्टेंस': 'inductance', 'रेजिस्टेंस': 'resistance', 'फ्रीक्वेंसी': 'frequency', 'वेवलेंथ': 'wavelength',
    'सॉल्यूशंस': 'solutions', 'राउल्ट्स': 'raoults', 'वेपर': 'vapor', 'प्रेशर': 'pressure',
    'हेलोएल्केन्स': 'haloalkanes', 'न्यूक्लियोफिलिक': 'nucleophilic', 'सबस्टिट्यूशन': 'substitution',
    'प्रोबेबिलिटी': 'probability', 'यूनियन': 'union', 'डायरेक्शन': 'direction', 'कोसाइन': 'cosines',
    'ग्रेविटेशन': 'gravitation', 'यूनिवर्सल': 'universal', 'फोर्स': 'force', 'वेव': 'waves', 'डॉपलर': 'doppler',
    'इफेक्ट': 'effect', 'फ्रीक्वेंसी': 'frequency', 'शिफ्ट': 'shift', 'इलेक्ट्रोस्टैटिक्स': 'electrostatics', 'कूलम्ब': 'coulomb'
}

def normalize_devanagari_to_roman(text: str) -> str:
    """Normalizes Devanagari script returned by Saaras v3 to Romanized Hinglish."""
    if not text:
        return ""
    words = text.split()
    norm_words = []
    for w in words:
        clean_w = w.strip()
        if clean_w in DEVANAGARI_ROMAN_MAP:
            norm_words.append(DEVANAGARI_ROMAN_MAP[clean_w])
        else:
            # Simple fallback character mapping for unmapped Devanagari words
            translated = clean_w
            for k, v in DEVANAGARI_ROMAN_MAP.items():
                translated = translated.replace(k, v)
            norm_words.append(translated)
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

    async def connect_and_stream(
        self,
        audio_stream: AsyncGenerator[bytes, None],
        on_transcript: Callable[[str, str, bool, float], None],
        on_barge_in: Callable[[], None]
    ):
        """Connects to Sarvam Saaras v3 endpoint and streams audio PCM chunks."""
        backoff = 1.0
        max_backoff = 15.0

        headers = {"api-key": SARVAM_API_KEY}
        params = f"?model={self.model}&mode={self.mode}&latency={self.latency_profile}"
        uri = f"{SARVAM_STT_ENDPOINT}{params}"

        while True:
            try:
                if SARVAM_API_KEY == "mock-sarvam-key" or "mock" in SARVAM_STT_ENDPOINT:
                    self.is_connected = True
                    async for chunk in audio_stream:
                        if len(chunk) > 0:
                            on_barge_in()
                            await asyncio.sleep(0.01)
                    break

                async with websockets.connect(uri, extra_headers=headers) as ws:
                    self.is_connected = True
                    backoff = 1.0

                    async def send_audio():
                        async for chunk in audio_stream:
                            await ws.send(chunk)

                    async def receive_transcripts():
                        async for msg in ws:
                            data = json.loads(msg)
                            raw_transcript = data.get("transcript", "")
                            norm_transcript = normalize_devanagari_to_roman(raw_transcript)
                            is_final = data.get("is_final", False)
                            confidence = data.get("confidence", 0.95)

                            if data.get("speech_onset"):
                                on_barge_in()

                            on_transcript(raw_transcript, norm_transcript, is_final, confidence)

                    await asyncio.gather(send_audio(), receive_transcripts())
                    break

            except websockets.exceptions.ConnectionClosed as e:
                self.is_connected = False
                if 4000 <= e.code < 5000:
                    raise RuntimeError(f"Saaras STT 4xxx error (code {e.code}): {e.reason}")
                else:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2.0, max_backoff)
            except Exception as e:
                self.is_connected = False
                break

class RumikTTSProxy:
    """Streaming TTS synthesis via Sarvam / Rumik Silk (speaker 'anushka', model 'bulbul:v2')."""
    def __init__(self, speaker: str = "anushka", model: str = "bulbul:v2"):
        self.speaker = speaker
        self.model = model

    async def synthesize_text(self, text: str) -> bytes:
        """Calls Sarvam TTS API and returns raw decoded audio bytes (WAV/PCM)."""
        import requests

        sarvam_key = os.getenv("SARVAM_API_KEY", "").strip("\"'")
        if not sarvam_key or "mock" in sarvam_key:
            raise RuntimeError("Invalid or missing SARVAM_API_KEY for TTS synthesis")

        url = os.getenv("RUMIK_TTS_ENDPOINT", "https://api.sarvam.ai/text-to-speech")
        headers = {
            "api-subscription-key": sarvam_key,
            "Content-Type": "application/json"
        }
        payload = {
            "inputs": [text],
            "target_language_code": "hi-IN",
            "speaker": self.speaker,
            "pitch": 0,
            "pace": 1.05,
            "loudness": 1.5,
            "speech_sample_rate": 16000,
            "enable_preprocessing": True,
            "model": self.model
        }

        def _call_http():
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f"Sarvam TTS HTTP {resp.status_code} Error: {resp.text}")
            data = resp.json()
            audios = data.get("audios", [])
            if not audios:
                raise RuntimeError(f"Sarvam TTS returned empty audios array: {data}")
            return base64.b64decode(audios[0])

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _call_http)

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
