"""The Deepgram STT proxy's configuration, which is where the accuracy lives.

No network here — the live behaviour was measured by hand and is recorded in
the class docstring. What this pins is the configuration that produced it,
because every one of these settings was chosen against a measurement and would
look arbitrary to someone tidying up later.
"""

import pytest

from app.drona.voice_proxy import DeepgramSTTProxy


def test_language_is_always_multi_never_forced_english():
    """Forcing roman output destroys the transcript, it does not just restyle it.

    Measured on "Dekho, yahan par net force zero hai, isliye acceleration bhi
    zero hoga":

        multi -> देखो, यहाँ पर net force जीरो है, इसलिए acceleration भी जीरो होगा
        en    -> Dikho, Yahapar Net four-zero Hai, Isliye acceleration d zero hoga

    "net force zero" became "net four-zero" — a physics term turned into a
    number. So `multi` is not a preference for Hindi speakers; it is the only
    setting that keeps an English technical term intact inside a code-mixed
    sentence. It must hold for BOTH session languages.
    """
    for language in ("english", "hinglish"):
        assert DeepgramSTTProxy(language=language).language_code == "multi"


def test_the_url_carries_the_settings_that_were_measured():
    url = DeepgramSTTProxy(language="english")._url()
    assert "model=nova-3" in url          # nova-2 mangled the same audio harder
    assert "language=multi" in url
    assert "encoding=linear16" in url
    assert "sample_rate=16000" in url     # what the browser sends
    assert "interim_results=true" in url  # the live transcript box needs partials
    assert "vad_events=true" in url       # SpeechStarted drives the barge-in callback


def test_keyterms_reach_the_url_encoded():
    """A concept name with spaces and punctuation must survive into a query string."""
    p = DeepgramSTTProxy(keyterms=["Born-Haber Cycle", "VSEPR Theory and Molecular Geometry"])
    url = p._url()
    assert "keyterm=Born-Haber+Cycle" in url
    assert "keyterm=VSEPR+Theory+and+Molecular+Geometry" in url


def test_keyterms_are_capped_and_emptied_safely():
    # An unbounded chapter would build an unbounded connect URL.
    assert len(DeepgramSTTProxy(keyterms=[f"term {i}" for i in range(200)]).keyterms) == 40
    # Falsy entries must not become empty keyterm= params.
    assert DeepgramSTTProxy(keyterms=["", None, "real"]).keyterms == ["real"]
    assert DeepgramSTTProxy(keyterms=None).keyterms == []


def test_it_still_accepts_sarvams_constructor_vocabulary():
    """mode and latency_profile are Sarvam's words, accepted and ignored.

    Kept so the construction site in live_session_ws.py did not have to change
    shape during the swap. If they are ever removed, that call breaks.
    """
    p = DeepgramSTTProxy(mode="codemix", latency_profile="Fast", language="hinglish")
    assert p.mode == "codemix" and p.latency_profile == "Fast"


def test_it_exposes_everything_the_session_calls():
    # live_session_ws.py calls exactly these. A rename here is a runtime
    # AttributeError inside a live student session, which nothing else catches.
    for attr in ("connect_and_stream", "transcribe_audio_rest", "close",
                 "is_connected", "MAX_KEYTERMS"):
        assert hasattr(DeepgramSTTProxy(), attr), f"session calls .{attr}"


def test_devanagari_normalisation_is_still_in_the_path():
    """Deepgram returns Devanagari; the product wants roman Hinglish.

    The transform already existed for Sarvam and needs no change — but if the
    call were dropped, transcripts would silently switch script and the tutor
    would grade text the student cannot read back.
    """
    import inspect
    from app.drona import voice_proxy
    for fn in (DeepgramSTTProxy.connect_and_stream, DeepgramSTTProxy.transcribe_audio_rest):
        assert "normalize_devanagari_to_roman" in inspect.getsource(fn)
    assert voice_proxy.normalize_devanagari_to_roman("देखो, net force जीरो है") \
        .startswith("dekho")
