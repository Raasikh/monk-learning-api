from app.drona.voice_proxy import normalize_devanagari_to_roman

stem_20_terms = [
    ("इंटीग्रेशन", "integration"),
    ("क्लासिफिकेशन", "classification"),
    ("थर्मोडायनामिक्स", "thermodynamics"),
    ("फोटोसिंथेसिस", "photosynthesis"),
    ("इक्विलिब्रियम", "equilibrium"),
    ("डिफरेंसिएशन", "differentiation"),
    ("वेलोसिटी", "velocity"),
    ("ऑक्सीडेशन", "oxidation"),
    ("वेक्टर", "vector"),
    ("रेजोल्यूशन", "resolution"),
    ("मैट्रिक्स", "matrix"),
    ("मल्टीप्लिकेशन", "multiplication"),
    ("प्रोबेबिलिटी", "probability"),
    ("एंजियोस्पर्म्स", "angiosperms"),
    ("जिम्नोस्पर्म्स", "gymnosperms"),
    ("फिजियोलॉजी", "physiology"),
    ("बायोलॉजिकल", "biological"),
    ("ग्रेविटेशन", "gravitation"),
    ("इलेक्ट्रोस्टैटिक्स", "electrostatics"),
    ("हाइब्रिडाइजेशन", "hybridisation")
]

def run_normalizer_test():
    print("=========================================================================")
    print("F3 ACCURACY TEST: 20 DEVANAGARI STEM TECHNICAL TERMS TO ROMANIZED HINGLISH")
    print("=========================================================================")

    correct_count = 0
    for idx, (dev_input, expected_roman) in enumerate(stem_20_terms, 1):
        actual_output = normalize_devanagari_to_roman(dev_input)
        is_exact = (actual_output.lower().strip() == expected_roman.lower().strip())
        if is_exact:
            correct_count += 1
        status = "MATCH" if is_exact else "MISMATCH"
        print(f"[{idx:02d}] Devanagari: '{dev_input}' -> Transliterated: '{actual_output}' (Expected: '{expected_roman}') [{status}]")

    accuracy = correct_count / len(stem_20_terms)
    print("\n=========================================================================")
    print(f"EXACT-MATCH ACCURACY ON 20 STEM TECHNICAL TERMS: {correct_count}/20 ({accuracy:.0%})")
    print("=========================================================================")

if __name__ == '__main__':
    run_normalizer_test()
