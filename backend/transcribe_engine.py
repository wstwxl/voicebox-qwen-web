import torch
from transformers import WhisperProcessor, WhisperForConditionalGeneration
import librosa

class TranscribeEngine:
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.is_loaded = False

    def load_model(self):
        if self.is_loaded:
            return
        print(f"Loading Whisper Base on {self.device}...")
        model_id = "openai/whisper-base"
        self.processor = WhisperProcessor.from_pretrained(model_id)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_id).to(self.device)
        self.is_loaded = True
        print("Whisper Base loaded.")

    def transcribe(self, audio_path: str, language: str = None) -> str:
        self.load_model()
        
        # Load audio and resample to 16000 required by Whisper
        audio, sr = librosa.load(audio_path, sr=16000)
        
        inputs = self.processor(
            audio,
            sampling_rate=16000,
            return_tensors="pt"
        ).input_features.to(self.device)
        
        # Determine language for whisper
        forced_decoder_ids = None
        if language and language.lower() != "auto":
            # Map human readable to whisper lang codes if needed
            # whisper uses "zh", "en", "ja", etc.
            lang_map = {
                "chinese": "zh",
                "english": "en",
                "japanese": "ja",
                "korean": "ko",
                "german": "de",
                "french": "fr",
                "russian": "ru",
                "portuguese": "pt",
                "spanish": "es",
                "italian": "it"
            }
            mapped_lang = lang_map.get(language.lower(), language.lower())
            
            try:
                forced_decoder_ids = self.processor.get_decoder_prompt_ids(
                    language=mapped_lang,
                    task="transcribe"
                )
            except Exception as e:
                print(f"Warning: Whisper language {mapped_lang} not supported, falling back to auto.")

        with torch.no_grad():
            predicted_ids = self.model.generate(
                inputs,
                forced_decoder_ids=forced_decoder_ids
            )
        
        transcription = self.processor.batch_decode(
            predicted_ids,
            skip_special_tokens=True
        )[0]
        
        return transcription.strip()

transcribe_engine = TranscribeEngine()
