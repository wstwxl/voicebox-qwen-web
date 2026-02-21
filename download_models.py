import os
import argparse

# Force using domestic Hugging Face mirror to avoid connection timeouts MUST BE BEFORE IMPORT
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

from huggingface_hub import snapshot_download
def download_models(download_qwen_1_7b=True, download_qwen_0_6b=True, download_whisper=True):
    print("This script will download required AI models from Hugging Face into your local cache.")
    print("Ensure you have a stable and fast internet connection.")
    print("-" * 50)
    
    # 1. Download Qwen 1.7B
    if download_qwen_1_7b:
        print("\n[1/3] Downloading Qwen3-TTS 1.7B Model (approx 3.5GB)...")
        snapshot_download("Qwen/Qwen3-TTS-12Hz-1.7B-Base", resume_download=True)
        print("-> 1.7B downloaded successfully.")
        
    # 2. Download Qwen 0.6B
    if download_qwen_0_6b:
        print("\n[2/3] Downloading Qwen3-TTS 0.6B Model (approx 1.2GB)...")
        snapshot_download("Qwen/Qwen3-TTS-12Hz-0.6B-Base", resume_download=True)
        print("-> 0.6B downloaded successfully.")
        
    # 3. Download Whisper Base (for transcription)
    if download_whisper:
        print("\n[3/3] Downloading Whisper Base Model (approx 300MB)...")
        snapshot_download("openai/whisper-base", resume_download=True)
        print("-> Whisper base downloaded successfully.")
        
    print("\n" + "=" * 50)
    print("All models downloaded successfully! You can now start the application.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download voicebox models from HF.")
    parser.add_argument("--skip-1.7b", action="store_true", help="Skip downloading Qwen 1.7B")
    parser.add_argument("--skip-0.6b", action="store_true", help="Skip downloading Qwen 0.6B")
    parser.add_argument("--skip-whisper", action="store_true", help="Skip downloading Whisper")
    
    args = parser.parse_args()
    download_models(
        download_qwen_1_7b=not getattr(args, "skip_1.7b", False),
        download_qwen_0_6b=not getattr(args, "skip_0.6b", False),
        download_whisper=not getattr(args, "skip_whisper", False),
    )
