import os
from google.cloud import texttospeech

def list_voices():
    try:
        # Set credentials explicitly as found in settings.py
        # We assume the script is run from the project root
        creds_path = os.path.abspath("tts-test-457216-dba0925ed1e8.json")
        if os.path.exists(creds_path):
            os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = creds_path
            print(f"Using credentials from: {creds_path}")
        else:
            print(f"Warning: Credentials file not found at {creds_path}")

        client = texttospeech.TextToSpeechClient()
        response = client.list_voices()
        
        print(f"Total voices found: {len(response.voices)}")
        
        # Check specifically for other languages
        target_langs = ['it-IT', 'pt-BR', 'ja-JP', 'zh-CN', 'ru-RU']
        print("\n--- Best Voices for Other Languages ---")
        for lang in target_langs:
            print(f"\nChecking {lang}...")
            # Prefer Studio > Neural2 > Wavenet
            voices = [v for v in response.voices if lang in v.language_codes]
            studio = [v for v in voices if 'Studio' in v.name]
            neural2 = [v for v in voices if 'Neural2' in v.name]
            
            if studio:
                for v in studio: print(f"  [STUDIO] {v.name} ({v.ssml_gender})")
            elif neural2:
                for v in neural2[:3]: print(f"  [NEURAL2] {v.name} ({v.ssml_gender})")
            else:
                 print(f"  (Only standard/wavenet found)")
             
    except Exception as e:
        print(f"Error listing voices: {e}")

if __name__ == "__main__":
    list_voices()
