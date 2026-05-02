import os
import time
import requests
import json
import google.generativeai as genai

VALID_GEMINI_KEYS = [
    'AIzaSyBFa6ZZ7-xpgtnnJPSRhfQ1eaziZipLYbo', 
    'AIzaSyBS8VX3BDSyhmlRNfsNtj4bJoSncAQrx1k', 
    'AIzaSyBh6-uxvCwewkquh55q7K36_EtBh_cD4cg', 
    'AIzaSyBjdA_uD4lOzeIIA3zz5ES8061KTjqzK18', 
    'AIzaSyC82f9oN0sa29A1i3FSKVzWrC9jidP1knc', 
    'AIzaSyCIpsI4BZy9qL2vs7IfrJpYgAtfWz7CgAA', 
    'AIzaSyCTynAE1JLInzifyZVv69YsDZEK6g2mRSY', 
    'AIzaSyCeO5e0hZHKUahlPF64A1TQJl8H8bqPhjg', 
    'AIzaSyDp2ZeOgLZ19_LEEkzEQzb_yDsOnfip0y8'
]

print("--- TESTING MODELS FOR EACH KEY ---")
for key in VALID_GEMINI_KEYS:
    try:
        genai.configure(api_key=key)
        print(f"\nKey: ...{key[-4:]}")
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"  - {m.name}")
    except Exception as e:
        print(f"  Error with key ...{key[-4:]}: {e}")
