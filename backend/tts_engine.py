import torch
import os
import asyncio
from typing import Optional, Tuple
import soundfile as sf
import numpy as np
from pathlib import Path

# Try to import Qwen3TTSModel
try:
    from qwen_tts import Qwen3TTSModel
except ImportError:
    Qwen3TTSModel = None

class SimpleTTSEngine:
    def __init__(self, model_size="1.7B"):
        self.model_size = model_size
        self.model = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.lock = asyncio.Lock()
        
    async def load_model(self, target_model_size: str = "1.7B"):
        async with self.lock:
            if self.model is not None and self.model_size != target_model_size:
                print(f"[Engine] Unloading model {self.model_size} to load {target_model_size}...")
                del self.model
                self.model = None
                torch.cuda.empty_cache()
                
            if self.model is not None:
                return

            self.model_size = target_model_size
            model_id = f"Qwen/Qwen3-TTS-12Hz-{self.model_size}-Base"
            print(f"[Engine] Loading model {model_id} on {self.device}...")
            
            def _load():
                dtype = torch.float32 if self.device == "cpu" else torch.bfloat16
                kwargs = {
                    "device_map": self.device,
                    "torch_dtype": dtype,
                }
                # Request FlashAttention-2 if available in the environment to save VRAM and boost speed
                try:
                    import flash_attn
                    kwargs["attn_implementation"] = "flash_attention_2"
                    print("[Engine] FlashAttention-2 enabled for acceleration.")
                except ImportError:
                    print("[Engine] FlashAttention-2 module not found, using default attention.")
                    
                return Qwen3TTSModel.from_pretrained(
                    model_id,
                    **kwargs
                )
            self.model = await asyncio.to_thread(_load)
            print("[Engine] Model loaded successfully.")
            
    async def create_prompt(self, audio_path: str, reference_text: str, model_size: str = "1.7B") -> dict:
        await self.load_model(model_size)
        
        def _extract():
            return self.model.create_voice_clone_prompt(
                ref_audio=audio_path,
                ref_text=reference_text,
                x_vector_only_mode=False,
            )
            
        prompt = await asyncio.to_thread(_extract)
        return prompt
        
    async def generate_speech(
        self, 
        text: str, 
        voice_prompt: dict,
        language: str = "auto",
        instruct: Optional[str] = None,
        model_size: str = "1.7B"
    ) -> Tuple[np.ndarray, int]:
        await self.load_model(model_size)
        
        import copy
        
        # Prevent infinite generation loops caused by trailing unhandled full-width punctuations
        safe_text = text.replace('……', '...').replace('——', '--')
        safe_instruct = instruct.replace('……', '...').replace('——', '--') if instruct else None
        
        def _generate():
            # generate_voice_clone returns a tuple containing list of generated wav arrays, and sample_rate
            kwargs = {
                "text": safe_text,
                # Deepcopy prompt to prevent internal state mutation affecting subsequent chunks for the same speaker
                "voice_clone_prompt": copy.deepcopy(voice_prompt),
                "language": language
            }
            if safe_instruct:
                kwargs["instruct"] = safe_instruct
                
            return self.model.generate_voice_clone(**kwargs)
            
        async with self.lock:
            wavs, sample_rate = await asyncio.to_thread(_generate)
            
        return wavs[0], sample_rate

# Global engine instance
engine = SimpleTTSEngine()
