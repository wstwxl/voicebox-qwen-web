from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
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
import re
import base64
import json
import numpy as np
import logging
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# ============ 静默 uvicorn 默认刷屏日志 ============
logging.getLogger("uvicorn.access").disabled = True

# ============ 在线设备追踪器 ============
class DeviceTracker:
    TIMEOUT = 300  # 5分钟无活动判定离线
    
    def __init__(self):
        self.devices = {}  # {ip: last_active_time}
    
    def heartbeat(self, ip: str):
        now = time.time()
        is_new = ip not in self.devices or (now - self.devices.get(ip, 0) > self.TIMEOUT)
        self.devices[ip] = now
        if is_new:
            self._cleanup()
            print(f"\n📱 [设备上线] {ip} | 当前在线设备: {len(self.devices)} 台")
    
    def _cleanup(self):
        now = time.time()
        expired = [ip for ip, t in self.devices.items() if now - t > self.TIMEOUT]
        for ip in expired:
            del self.devices[ip]
            print(f"📴 [设备离线] {ip} 超过5分钟无活动 | 当前在线设备: {len(self.devices)} 台")
    
    def get_online_count(self):
        self._cleanup()
        return len(self.devices)

device_tracker = DeviceTracker()

# ============ GPU 显存报告 ============
def gpu_memory_report():
    if torch.cuda.is_available():
        used = torch.cuda.memory_allocated() / 1024**3
        total = torch.cuda.get_device_properties(0).total_mem / 1024**3
        pct = used / total * 100 if total > 0 else 0
        return f"📊 显存: {used:.1f}/{total:.1f} GB ({pct:.0f}%)"
    return "📊 显存: N/A (无CUDA)"

# ============ GPU 任务队列管理器 ============
class GPUQueue:
    def __init__(self):
        self.queue = []
        self.active = False
        self._task_meta = {}  # {task_id: {name, ip, start_time}}
        
    def register_meta(self, task_id: str, task_name: str, ip: str):
        self._task_meta[task_id] = {"name": task_name, "ip": ip, "start_time": None}
        
    async def acquire(self, task_id: str):
        if task_id not in self.queue:
            self.queue.append(task_id)
        meta = self._task_meta.get(task_id, {"name": "未知任务", "ip": "?"})
        pos = self.get_position(task_id)
        total = len(self.queue)
        if pos > 0:
            print(f"⏳ [任务排队] {meta.get('name')} | 来自 {meta.get('ip')} | 排在第 {pos+1} 位（前方 {pos} 个任务）")
        while self.queue[0] != task_id or self.active:
            await asyncio.sleep(0.5)
        self.active = True
        meta["start_time"] = time.time()
        print(f"🔥 [任务开始] {meta.get('name')} | 来自 {meta.get('ip')} | 队列: {len(self.queue)} 个任务")
        
    def release(self, task_id: str):
        meta = self._task_meta.pop(task_id, {"name": "未知任务", "ip": "?"})
        elapsed = time.time() - meta["start_time"] if meta.get("start_time") else 0
        self.active = False
        if task_id in self.queue:
            self.queue.remove(task_id)
        remaining = len(self.queue)
        mem = gpu_memory_report()
        print(f"✅ [任务完成] {meta.get('name')} | 来自 {meta.get('ip')} | 耗时 {elapsed:.1f}秒 | {mem}")
        if remaining == 0:
            print(f"💤 [服务器空闲] 当前无任务运行、无任务排队 | 在线设备: {device_tracker.get_online_count()} 台")
        else:
            print(f"   └─ 队列中还有 {remaining} 个任务等待处理")
            
    def get_position(self, task_id: str):
        try:
            return self.queue.index(task_id)
        except ValueError:
            return -1

gpu_queue = GPUQueue()

app = FastAPI(title="Voicebox Local Server")

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

# ============ 设备追踪中间件 ============
class DeviceTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host if request.client else "unknown"
        device_tracker.heartbeat(ip)
        response = await call_next(request)
        return response

app.add_middleware(DeviceTrackingMiddleware)


@app.on_event("startup")
async def startup_event():
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    
    # 统计已有数据
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM profiles")
    profile_count = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM history")
    history_count = c.fetchone()[0]
    
    # ============ 启动清理 ============
    # 1. 清理 data/temp/ 目录（全是临时文件，没有保留价值）
    temp_dir = DATA_DIR / "temp"
    temp_cleaned = 0
    temp_freed_bytes = 0
    if temp_dir.exists():
        for f in temp_dir.iterdir():
            if f.is_file():
                temp_freed_bytes += f.stat().st_size
                f.unlink()
                temp_cleaned += 1
    
    # 2. 清理 data/profiles/ 中的孤儿文件夹（数据库里没有注册的）
    c.execute("SELECT id FROM profiles")
    registered_ids = {row[0] for row in c.fetchall()}
    conn.close()
    
    orphan_cleaned = 0
    orphan_freed_bytes = 0
    if PROFILES_DIR.exists():
        for folder in PROFILES_DIR.iterdir():
            if folder.is_dir() and folder.name not in registered_ids:
                # 计算文件夹大小
                for f in folder.rglob("*"):
                    if f.is_file():
                        orphan_freed_bytes += f.stat().st_size
                shutil.rmtree(folder)
                orphan_cleaned += 1
    
    # 3. history/ 下的文件全部保留，不做任何处理
    
    # GPU 信息
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "无CUDA"
    gpu_mem = f"{torch.cuda.get_device_properties(0).total_mem / 1024**3:.0f}GB" if torch.cuda.is_available() else "N/A"
    
    total_freed_mb = (temp_freed_bytes + orphan_freed_bytes) / 1024 / 1024
    
    print("\n" + "=" * 55)
    print("    🎙️  Voicebox Qwen Web UI (云端多用户版)")
    print(f"    📡 监听端口: 6006")
    print(f"    🎮 GPU: {gpu_name} | 显存: {gpu_mem}")
    print(f"    📦 已有音色: {profile_count} 个 | 历史记录: {history_count} 条")
    print(f"    ⏰ 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if temp_cleaned > 0 or orphan_cleaned > 0:
        print(f"    🧹 启动清理: 删除 {temp_cleaned} 个临时文件 + {orphan_cleaned} 个孤儿音色 | 释放 {total_freed_mb:.1f} MB")
    else:
        print(f"    🧹 启动清理: 磁盘很干净，无需清理 ✨")
    print("=" * 55)
    print("    等待用户连接中...\n")


@app.post("/api/queue_register")
async def queue_register():
    """Frontend calls this BEFORE sending GPU work to get a personal queue ticket."""
    task_id = str(uuid.uuid4())
    gpu_queue.queue.append(task_id)
    pos = gpu_queue.get_position(task_id)
    return {"task_id": task_id, "position": pos, "total": len(gpu_queue.queue)}

@app.get("/api/queue_position/{task_id}")
async def queue_position(task_id: str):
    """Get the position of a specific task in the queue."""
    pos = gpu_queue.get_position(task_id)
    return {"task_id": task_id, "position": pos, "total": len(gpu_queue.queue), "is_active": gpu_queue.active}

@app.post("/api/profiles", response_model=ProfileResponse)
async def create_profile(
    request: Request,
    audio: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    reference_text: str = Form(...),
    task_id: str = Form(None)
):
    if not task_id:
        task_id = str(uuid.uuid4())
    gpu_queue.register_meta(task_id, "音色提取", request.client.host if hasattr(request, 'client') and request.client else "?")
    await gpu_queue.acquire(task_id)
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
    finally:
        gpu_queue.release(task_id)

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
    request: Request,
    audio: UploadFile = File(...),
    language: str = Form("auto"),
    task_id: str = Form(None)
):
    if not task_id:
        task_id = str(uuid.uuid4())
    gpu_queue.register_meta(task_id, "语音听写", request.client.host if hasattr(request, 'client') and request.client else "?")
    await gpu_queue.acquire(task_id)
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
    finally:
        gpu_queue.release(task_id)

@app.post("/api/generate", response_model=HistoryResponse)
async def generate_audio(
    request: Request,
    profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("auto"),
    model_size: str = Form("1.7B"),
    instruct: str = Form(None),
    task_id: str = Form(None)
):
    if not task_id:
        task_id = str(uuid.uuid4())
    gpu_queue.register_meta(task_id, "普通合成", request.client.host if hasattr(request, 'client') and request.client else "?")
    await gpu_queue.acquire(task_id)
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
    finally:
        gpu_queue.release(task_id)

def split_text_to_chunks(text: str) -> list:
    """Split text into sentence-level chunks for streaming generation."""
    # Split on Chinese/English sentence endings
    parts = re.split(r'(?<=[。！？；\n.!?;])', text)
    chunks = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # If chunk is very short, merge with previous
        if chunks and len(chunks[-1]) < 8:
            chunks[-1] += p
        else:
            chunks.append(p)
    # If no splitting happened, return whole text
    if not chunks:
        chunks = [text]
    return chunks

@app.post("/api/generate_stream")
async def generate_audio_stream(
    request: Request,
    profile_id: str = Form(...),
    text: str = Form(...),
    language: str = Form("auto"),
    model_size: str = Form("1.7B"),
    instruct: str = Form(None),
    task_id: str = Form(None)
):
    if not task_id:
        task_id = str(uuid.uuid4())
    # Register metadata for logging
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    gpu_queue.register_meta(task_id, "流式合成", client_ip)
    # Register the task in the wait queue (supports pre-registered tickets)
    if task_id not in gpu_queue.queue:
        gpu_queue.queue.append(task_id)

    async def event_generator():
        try:
            # Emit queue events while waiting
            while True:
                pos = gpu_queue.get_position(task_id)
                yield f"data: {json.dumps({'type': 'queue', 'position': pos})}\n\n"
                if gpu_queue.queue[0] == task_id and not gpu_queue.active:
                    break
                await asyncio.sleep(1.0)
                
            # Now we are at the front, acquire GPU lock
            gpu_queue.active = True
            
            # Now execution continues matching before
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,))
            profile_row = c.fetchone()
            
            if not profile_row:
                conn.close()
                yield f"data: {json.dumps({'type': 'error', 'message': 'Profile not found'})}\n\n"
                return
                
            profile_folder = PROFILES_DIR / profile_id
            prompt_file = profile_folder / f"prompt_{model_size}.pt"
            
            if not prompt_file.exists():
                source_audio = profile_folder / "source.wav"
                ref_txt_file = profile_folder / "reference.txt"
                if not source_audio.exists() or not ref_txt_file.exists():
                    yield f"data: {json.dumps({'type': 'error', 'message': 'Missing source audio for this profile'})}\n\n"
                    return
                with open(ref_txt_file, "r", encoding="utf-8") as f:
                    ref_text = f.read()
                prompt = await engine.create_prompt(str(source_audio), ref_text, model_size=model_size)
                torch.save(prompt, prompt_file)
            else:
                prompt = torch.load(prompt_file, weights_only=False)
            
            chunks = split_text_to_chunks(text)
            total_chunks = len(chunks)
            all_audio_arrays = []
            sample_rate = 24000
            
            yield f"data: {json.dumps({'type': 'info', 'total_chunks': total_chunks})}\n\n"
            
            for idx, chunk_text in enumerate(chunks):
                try:
                    audio_array, sr = await engine.generate_speech(
                        text=chunk_text,
                        voice_prompt=prompt,
                        language=language,
                        instruct=instruct,
                        model_size=model_size
                    )
                    sample_rate = sr
                    all_audio_arrays.append(audio_array)
                    
                    # Encode audio chunk as base64 wav
                    buf = io.BytesIO()
                    sf.write(buf, audio_array, sr, format='WAV')
                    buf.seek(0)
                    audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                    
                    yield f"data: {json.dumps({'type': 'chunk', 'index': idx, 'total': total_chunks, 'audio_b64': audio_b64, 'text': chunk_text})}\n\n"
                except Exception as chunk_err:
                    traceback.print_exc()
                    yield f"data: {json.dumps({'type': 'chunk_error', 'index': idx, 'message': str(chunk_err)})}\n\n"
            
            # Save complete audio to history
            if all_audio_arrays:
                full_audio = np.concatenate(all_audio_arrays)
                dur = len(full_audio) / sample_rate
                gen_id = str(uuid.uuid4())
                audio_file = HISTORY_DIR / f"{gen_id}.wav"
                sf.write(str(audio_file), full_audio, sample_rate)
                
                c.execute(
                    "INSERT INTO history (id, profile_id, text, language, instruct, audio_path, duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (gen_id, profile_id, text, language, instruct, str(audio_file), dur)
                )
                conn.commit()
                conn.close()
                
                yield f"data: {json.dumps({'type': 'done', 'history_id': gen_id, 'duration': dur})}\n\n"
            else:
                conn.close()
                yield f"data: {json.dumps({'type': 'error', 'message': 'No audio generated'})}\n\n"
                
        except Exception as e:
            traceback.print_exc()
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            gpu_queue.release(task_id)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/queue_status")
async def queue_status():
    return {"tasks_in_queue": len(gpu_queue.queue), "is_active": gpu_queue.active}

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

