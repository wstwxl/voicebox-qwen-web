from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import uuid
import os
import shutil
import time
import torch
import zipfile
import io
from pathlib import Path

from .schemas import ProfileResponse, HistoryResponse, BatchDownloadRequest
from .database import get_db_connection
from .tts_engine import engine
from .transcribe_engine import transcribe_engine
import soundfile as sf
import traceback
import asyncio

app = FastAPI(title="Voicebox Local")

# Configure paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILES_DIR = DATA_DIR / "profiles"
HISTORY_DIR = DATA_DIR / "history"
STATIC_DIR = BASE_DIR / "static"

from . import database

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    print("Voicebox Local Server Started on port 8888")


@app.post("/api/profiles", response_model=ProfileResponse)
async def create_profile(
    audio: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    reference_text: str = Form(...)
):
    try:
        profile_id = str(uuid.uuid4())
        profile_folder = PROFILES_DIR / profile_id
        profile_folder.mkdir(parents=True, exist_ok=True)
        
        source_audio_path = profile_folder / "source.wav"
        with open(source_audio_path, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
            
        # Save reference text side-by-side
        with open(profile_folder / "reference.txt", "w", encoding="utf-8") as f:
            f.write(reference_text)
            
        # Create prompts for both 1.7B and 0.6B dynamically
        prompt_1_7B = await engine.create_prompt(str(source_audio_path), reference_text, model_size="1.7B")
        prompt_1_7B_path = profile_folder / "prompt_1.7B.pt"
        torch.save(prompt_1_7B, prompt_1_7B_path)
        
        prompt_0_6B = await engine.create_prompt(str(source_audio_path), reference_text, model_size="0.6B")
        prompt_0_6B_path = profile_folder / "prompt_0.6B.pt"
        torch.save(prompt_0_6B, prompt_0_6B_path)
        
        # Save to DB
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO profiles (id, name, description, prompt_path) VALUES (?, ?, ?, ?)",
            (profile_id, name, description, str(prompt_1_7B_path))
        )
        conn.commit()
        
        c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,))
        row = c.fetchone()
        conn.close()
        
        # We no longer delete temp audio; it was renamed to source.wav
        return dict(row)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/profiles", response_model=list[ProfileResponse])
async def list_profiles():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    conn.commit()
    conn.close()
    
    # delete files
    folder = PROFILES_DIR / profile_id
    if folder.exists():
        shutil.rmtree(folder)
    return {"message": "deleted"}


@app.post("/api/transcribe")
async def transcribe_audio_endpoint(
    audio: UploadFile = File(...),
    language: str = Form("auto")
):
    try:
        temp_dir = Path("data/temp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_file = temp_dir / f"transcribe_{uuid.uuid4()}.wav"
        
        with open(temp_file, "wb") as buffer:
            shutil.copyfileobj(audio.file, buffer)
            
        # Run transcription
        def _do_transcribe():
            return transcribe_engine.transcribe(str(temp_file), language)
            
        transcription = await asyncio.to_thread(_do_transcribe)
        
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()
            
        return {"text": transcription}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/generate", response_model=HistoryResponse)
async def generate_audio(
    profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("auto"),
    model_size: str = Form("1.7B"),
    instruct: str = Form(None)
):
    try:
        # Get profile
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,))
        profile_row = c.fetchone()
        
        if not profile_row:
            conn.close()
            raise HTTPException(status_code=404, detail="Profile not found")
            
        profile_folder = PROFILES_DIR / profile_id
        prompt_file = profile_folder / f"prompt_{model_size}.pt"
        
        if not prompt_file.exists():
            # If prompt for this model doesn't exist, try dynamically creating it from source
            source_audio = profile_folder / "source.wav"
            ref_txt_file = profile_folder / "reference.txt"
            
            if not source_audio.exists() or not ref_txt_file.exists():
                raise HTTPException(status_code=400, detail=f"该音色是旧版迁移过来的，缺失原音频无法直接为您动态生成 {model_size} 的音色向量张量。请使用 1.7B 或者重新录制此音色。")
                
            with open(ref_txt_file, "r", encoding="utf-8") as f:
                ref_text = f.read()
                
            prompt = await engine.create_prompt(str(source_audio), ref_text, model_size=model_size)
            torch.save(prompt, prompt_file)
        else:
            prompt = torch.load(prompt_file, weights_only=False)
        
        start_time = time.time()
        audio_array, sr = await engine.generate_speech(
            text=text, 
            voice_prompt=prompt, 
            language=language, 
            instruct=instruct,
            model_size=model_size
        )
        dur = len(audio_array) / sr
        
        gen_id = str(uuid.uuid4())
        audio_file = HISTORY_DIR / f"{gen_id}.wav"
        sf.write(str(audio_file), audio_array, sr)
        
        c.execute(
            "INSERT INTO history (id, profile_id, text, language, instruct, audio_path, duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (gen_id, profile_id, text, language, instruct, str(audio_file), dur)
        )
        conn.commit()
        
        c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id WHERE h.id=?", (gen_id,))
        history_row = c.fetchone()
        conn.close()
        
        return dict(history_row)
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/history", response_model=list[HistoryResponse])
async def list_history():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id ORDER BY h.created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/history/{history_id}")
async def delete_history(history_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT audio_path FROM history WHERE id=?", (history_id,))
    row = c.fetchone()
    if row:
        audio_file = Path(row["audio_path"])
        if audio_file.exists():
            audio_file.unlink()
            
    c.execute("DELETE FROM history WHERE id=?", (history_id,))
    conn.commit()
    conn.close()
    return {"message": "deleted"}

@app.post("/api/history/batch_download")
async def batch_download(req: BatchDownloadRequest):
    if not req.ids:
        raise HTTPException(status_code=400, detail="No IDs provided")
        
    conn = get_db_connection()
    c = conn.cursor()
    placeholders = ",".join(["?"] * len(req.ids))
    
    # query history, sort by creation time ASC to order from old to new
    query = f"""
        SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name 
        FROM history h 
        LEFT JOIN profiles p ON h.profile_id = p.id 
        WHERE h.id IN ({placeholders})
        ORDER BY h.created_at ASC
    """
    c.execute(query, req.ids)
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        raise HTTPException(status_code=404, detail="No valid records found")
        
    # Create zip file in memory
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zf:
        for idx, row in enumerate(rows, start=1):
            audio_path = Path(row["audio_path"])
            if audio_path.exists():
                dur_str = f"{row['duration']:.1f}s"
                safe_name = f"{row['profile_name']}-{row['language']}-{dur_str}.wav".replace(" ", "_")
                # format index number in front of the name
                zip_filename = f"{idx}-{safe_name}"
                zf.write(audio_path, arcname=zip_filename)
                
    memory_file.seek(0)
    
    return Response(
        content=memory_file.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=\"voicebox_batch.zip\""}
    )

@app.get("/audio/history/{history_id}")
async def get_history_audio(history_id: str):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id WHERE h.id=?", (history_id,))
    row = c.fetchone()
    conn.close()
    if not row:
         raise HTTPException(status_code=404, detail="Not found")
         
    # Generate download filename: 音色名字-语种-时间长度.wav
    dur_str = f"{row['duration']:.1f}s"
    safe_name = f"{row['profile_name']}-{row['language']}-{dur_str}.wav".replace(" ", "_")
    
    return FileResponse(row["audio_path"], filename=safe_name, media_type="audio/wav")

@app.get("/audio/profiles/{profile_id}")
async def get_profile_audio(profile_id: str):
    audio_path = PROFILES_DIR / profile_id / "source.wav"
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(audio_path, media_type="audio/wav")

# Mount Static Files (the UI)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

