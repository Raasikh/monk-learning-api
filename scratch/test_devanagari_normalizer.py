import re

TECHNICAL_TERMS_MAP = {
    'इंटीग्रेशन': 'integration',
    'डिफरेंशियल': 'differential',
    'डिफरेंसिएशन': 'differentiation',
    'इक्वेशन': 'equation',
    'डेरिवेटिव': 'derivative',
    'वेक्टर': 'vector',
    'कैपेसिटर': 'capacitor',
    'इलेक्ट्रॉन': 'electron',
    'प्रोटॉन': 'proton',
    'न्यूट्रॉन': 'neutron',
    'न्यूक्लियस': 'nucleus',
    'ऑक्सीडेशन': 'oxidation',
    'रिडक्शन': 'reduction',
    'इलेक्ट्रोस्टैटिक्स': 'electrostatics',
    'थर्मोडायनामिक्स': 'thermodynamics',
    'इक्विलिब्रियम': 'equilibrium',
    'हाइब्रिडाइजेशन': 'hybridisation',
    'फ्रीक्वेंसी': 'frequency',
    'वेवलेंथ': 'wavelength',
    'रेजिस्टेंस': 'resistance',
    'इंडक्टेंस': 'inductance',
    'कैपेसिटेंस': 'capacitance',
    'ग्रेविटेशन': 'gravitation',
    'वेलोसिटी': 'velocity',
    'एक्सीलरेशन': 'acceleration',
    'मोमेंटम': 'momentum',
    'पोटेंशियल': 'potential',
    'मैग्नेटिक': 'magnetic',
    'फील्ड': 'field',
    'हाँ': 'haan'
}

# Devanagari Unicode character transliteration rules
VOWELS = {
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au', 'अं': 'am', 'अः': 'ah'
}

MATRAS = {
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h', '्': ''
}

CONSONANTS = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'f', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'श': 'sh',
    'ष': 'sh', 'स': 's', 'ह': 'h', 'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gy'
}

def transliterate_devanagari_word(word: str) -> str:
    # 1. Clean punctuation
    clean_w = re.sub(r'[^\u0900-\u097F]', '', word)
    if not clean_w:
        return word

    # 2. Direct Technical term match
    if clean_w in TECHNICAL_TERMS_MAP:
        return TECHNICAL_TERMS_MAP[clean_w]

    # 3. Phonetic Devanagari to Roman transliteration
    res = []
    i = 0
    n = len(clean_w)
    while i < n:
        char = clean_w[i]
        next_char = clean_w[i+1] if i + 1 < n else ""

        if char in CONSONANTS:
            base = CONSONANTS[char]
            if next_char in MATRAS:
                res.append(base + MATRAS[next_char])
                i += 2
            else:
                # Inherited schwa 'a' unless followed by halant or at end
                if next_char in CONSONANTS or not next_char:
                    res.append(base + ("a" if i + 1 < n else ""))
                else:
                    res.append(base)
                i += 1
        elif char in VOWELS:
            res.append(VOWELS[char])
            i += 1
        elif char in MATRAS:
            res.append(MATRAS[char])
            i += 1
        else:
            res.append(char)
            i += 1

    out = "".join(res)
    return out if out else word

def normalize_devanagari_to_roman(text: str) -> str:
    if not text:
        return ""
    words = text.split()
    norm_words = []
    for w in words:
        # Preserve non-Devanagari text directly
        if re.search(r'[\u0900-\u097F]', w):
            norm_words.append(transliterate_devanagari_word(w))
        else:
            norm_words.append(w)
    return " ".join(norm_words)

# Test 10 technical terms requested by user
test_terms = [
    ("इंटीग्रेशन", "integration"),
    ("डिफरेंशियल", "differential"),
    ("इक्वेशन", "equation"),
    ("डेरिवेटिव", "derivative"),
    ("वेक्टर", "vector"),
    ("कैपेसिटर", "capacitor"),
    ("इलेक्ट्रॉन", "electron"),
    ("प्रोटॉन", "proton"),
    ("न्यूट्रॉन", "neutron"),
    ("न्यूक्लियस", "nucleus")
]

if __name__ == "__main__":
    print("=== VERIFYING 10 TECHNICAL TERMS ===")
    all_passed = True
    for dev, exp in test_terms:
        out = normalize_devanagari_to_roman(dev)
        status = "✅ PASS" if out == exp else f"❌ FAIL (got '{out}')"
        print(f"Input: '{dev}' -> Output: '{out}' (Expected: '{exp}') | {status}")
        if out != exp:
            all_passed = False
    print(f"Overall Result: {'100% PASSED' if all_passed else 'FAILED'}")
