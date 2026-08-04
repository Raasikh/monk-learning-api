from app.drona.voice_proxy import normalize_devanagari_to_roman

# 10 STEM / Hinglish terms deliberately outside the exact DEVANAGARI_ROMAN_MAP dictionary
out_of_dict_10 = [
    ("रेडिएशन", "radiatiion"),
    ("न्यूक्लियस", "nucleus"),
    ("इलेक्ट्रॉन", "electron"),
    ("प्रोटॉन", "proton"),
    ("न्यूट्रॉन", "neutron"),
    ("कैपेसिटेंस", "capacitance"),
    ("इंडक्टेंस", "inductance"),
    ("रेजिस्टेंस", "resistance"),
    ("फ्रीक्वेंसी", "frequency"),
    ("वेवलेंथ", "wavelength")
]

def run_out_of_dict_test():
    print("=========================================================================")
    print("STT NORMALIZER OUT-OF-DICTIONARY FALLBACK TEST (10 UNMAPPED DEVANAGARI TERMS)")
    print("=========================================================================")

    for idx, (dev_in, concept) in enumerate(out_of_dict_10, 1):
        norm_out = normalize_devanagari_to_roman(dev_in)
        print(f"[{idx:02d}] Unmapped Input: '{dev_in}' (Concept: {concept}) -> Normalizer Output: '{norm_out}'")

    print("\n[EXPLANATION OF UNMAPPED BEHAVIOR]:")
    print("When an unmapped Devanagari token is encountered, the normalizer passes the original token through or applies character transliteration without throwing an exception or blocking the turn. For 100% exact English STEM term recovery, terms are added to DEVANAGARI_ROMAN_MAP in app/drona/voice_proxy.py.")
    print("=========================================================================")

if __name__ == '__main__':
    run_out_of_dict_test()
