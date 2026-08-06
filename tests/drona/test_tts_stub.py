import os
os.environ["RUMIK_API_KEY"] = "rk_live_stub_key_12345"
os.environ["SARVAM_API_KEY"] = "sarvam_stub_key_12345"

import unittest
from unittest.mock import patch, MagicMock
import asyncio

class TestRumikTTSProxyStub(unittest.TestCase):
    """Unit test calling RumikTTSProxy.synthesize_text() against a stub to ensure call-time execution cleanly returns bytes without NameError or scope errors."""

    @patch("app.drona.voice_proxy.requests.post")
    @patch("app.drona.voice_proxy.websockets.connect")
    def test_synthesize_text_success_stub(self, mock_ws_connect, mock_http_post):
        from app.drona.voice_proxy import RumikTTSProxy

        # Stub HTTP mint handshake response
        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = {
            "ws_url": "wss://silk-api.rumik.ai/v1/tts/ws",
            "token": "stub_token_123"
        }
        mock_http_post.return_value = mock_http_resp

        # Stub WebSocket connection yielding PCM bytes then done frame
        mock_ws = MagicMock()
        
        async def mock_recv():
            # First call returns PCM audio bytes
            if not getattr(mock_recv, "called", False):
                mock_recv.called = True
                return b"\x00\x01" * 8000
            # Second call returns done control frame
            return '{"type": "done"}'

        mock_ws.recv = mock_recv
        mock_ws.send = MagicMock(return_value=asyncio.sleep(0))

        # Async context manager mock for websockets.connect
        class MockWSContextManager:
            async def __aenter__(self):
                return mock_ws
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        mock_ws_connect.return_value = MockWSContextManager()

        tts = RumikTTSProxy(voice_preset="Ira", model="mulberry")
        
        # Execute synthesize_text at call-time
        audio_bytes = asyncio.run(tts.synthesize_text("Bilkul sahi! Test sentence."))

        self.assertIsInstance(audio_bytes, bytes)
        self.assertGreater(len(audio_bytes), 0)
        self.assertEqual(len(audio_bytes), 16000)

if __name__ == "__main__":
    unittest.main()
