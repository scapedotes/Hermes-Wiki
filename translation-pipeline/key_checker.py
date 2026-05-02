import os
import time
import requests
import json

GEMINI_KEYS = ['AIzaSyA3VkLUoMxyG8e3q3HGa-CSw548txKtVQo', 'AIzaSyAEZ6ttFSsd3W8Xv5As3AHIwWCeaFQ90qk', 'AIzaSyAG8GnkhVmP4-xcVkbd6JQY8luOWR3ZQvg', 'AIzaSyAKlbqhApEri0ZVKIv5ZGrMrEULLrYQWPM', 'AIzaSyAVqHaHBRos1lRKk5hi62mC9W7ssz3bzTw', 'AIzaSyA_rZoxcgGK_7H-lTMzV5oJqoU_vrZfSSc', 'AIzaSyB4MusZbkPPSbPjPxNMFfGnT4yj7HKQC2c', 'AIzaSyB4w4ILwDvsCqjoMsfqHGynNZCEE2VBHvg', 'AIzaSyBFKq4XRb505EOdPiy3O7Gt3D192siUr30', 'AIzaSyBFa6ZZ7-xpgtnnJPSRhfQ1eaziZipLYbo', 'AIzaSyBS8VX3BDSyhmlRNfsNtj4bJoSncAQrx1k', 'AIzaSyBVoVCLoniXGeNErSz4iNSWtqqoMrETg-Q', 'AIzaSyBWZMFT-QRim0VYkB_610mMJix13s01ynk', 'AIzaSyBh6-uxvCwewkquh55q7K36_EtBh_cD4cg', 'AIzaSyBjdA_uD4lOzeIIA3zz5ES8061KTjqzK18', 'AIzaSyBsUsMJpHh7hphROcVHDZJ3qmYS83Lkq-k', 'AIzaSyC82f9oN0sa29A1i3FSKVzWrC9jidP1knc', 'AIzaSyCIpsI4BZy9qL2vs7IfrJpYgAtfWz7CgAA', 'AIzaSyCKFaJ_1EPvsfw6V00pdGEi__u8XfyapqA', 'AIzaSyCTynAE1JLInzifyZVv69YsDZEK6g2mRSY', 'AIzaSyCZZWXvGNj9GuK6baeVfspONJl2UlM8aEc', 'AIzaSyCeO5e0hZHKUahlPF64A1TQJl8H8bqPhjg', 'AIzaSyChRuLP-xS8ucyyu1xbBiE-hrHTti_Ks5E', 'AIzaSyCv8Dd_4oURTJLOyuaD7aA11wnFfytvsCk', 'AIzaSyDL5Za6UnrXtvoEVf-PbJtExiWVBAECoMg', 'AIzaSyDTCx9Zkaw8A_ncrAGAj9_6SjeOxQevBtc', 'AIzaSyDWJm1cjj7dgLlPBtkXTmmU1Fsj_suGMv0', 'AIzaSyDWjAGYMsP9yEDC3xTQOCMApxcCmfHx48I', 'AIzaSyDp2ZeOgLZ19_LEEkzEQzb_yDsOnfip0y8']

class KeyChecker:
    def check_gemini(self, key):
        # Using a very basic models list call to check key validity without assuming model availability
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                models = resp.json().get('models', [])
                model_names = [m['name'] for m in models]
                return True, f"OK - Found {len(models)} models: {model_names[:3]}..."
            data = resp.json()
            error_msg = data.get('error', {}).get('message', 'Unknown error')
            return False, f"HTTP {resp.status_code}: {error_msg}"
        except Exception as e:
            return False, str(e)

if __name__ == "__main__":
    checker = KeyChecker()
    valid = []
    print(f"Testing {len(GEMINI_KEYS)} keys via ListModels...")
    for i, k in enumerate(GEMINI_KEYS):
        ok, msg = checker.check_gemini(k)
        status = "✓" if ok else "✗"
        print(f"[{i+1}/{len(GEMINI_KEYS)}] {status} Key [...{k[-4:]}]: {msg}")
        if ok:
            valid.append(k)
    
    print(f"\nVALID_GEMINI_KEYS = {valid}")
