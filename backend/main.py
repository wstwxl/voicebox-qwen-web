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
        total = torch.cuda.get_device_properties(0).total_memory / 1024**3
        pct = used / total * 100 if total > 0 else 0
        return f"📊 显存: {used:.1f}/{total:.1f} GB ({pct:.0f}%)"
    return "📊 显存: N/A (无CUDA)"

# ============ GPU 任务队列管理器 (重构版) ============
job_queue = asyncio.Queue()

# Thread-safe dictionary to track state of each job
# { task_id: {"status": "queued"|"processing"|"done"|"error", "result": dict, "error": str, "type": "...", "created_at": float, "name": str, "ip": str} }
job_statuses = {}

# 全局流式缓冲池 (供流式合成 API 与后台 Worker 传递 chunk 使用)
stream_buffers = {} # { task_id: asyncio.Queue() }

async def bg_gpu_worker():
    """全局唯一的 GPU 任务守护者协程。无论外部 HTTP 怎么断，它都不会死，直到算完存盘。"""
    print("🚀 [后台守护进程] GPU 任务流水线已启动。开始监听全局队列...")
    while True:
        try:
            task = await job_queue.get()
            task_id = task["task_id"]
            task_type = task["type"]
            meta_name = task.get("name", "未知任务")
            ip = task.get("ip", "?")
            
            # 如果请求已经被前端明确地标记为已丢弃(在等待期间刷走了)
            if job_statuses.get(task_id, {}).get("status") == "cancelled":
                print(f"⏩ [任务跳过] {meta_name} | 来自 {ip} | 任务已被客户端丢弃，跳过执行。")
                job_queue.task_done()
                continue
                
            job_statuses[task_id]["status"] = "processing"
            start_t = time.time()
            
            # 查一下排在队列第一位等待的还有哪些
            pos_info = f" | 队列剩余待办: {job_queue.qsize()}"
            print(f"🔥 [任务开始] {meta_name} | 来自 {ip}{pos_info}")
            
            try:
                if task_type == "extract_profile":
                    res = await _handle_extract_profile(task)
                    job_statuses[task_id]["status"] = "done"
                    job_statuses[task_id]["result"] = res
                    
                elif task_type == "transcribe":
                    res = await _handle_transcribe(task)
                    job_statuses[task_id]["status"] = "done"
                    job_statuses[task_id]["result"] = res
                    
                elif task_type == "generate":
                    res = await _handle_generate(task)
                    job_statuses[task_id]["status"] = "done"
                    job_statuses[task_id]["result"] = res
                    
                elif task_type == "generate_stream":
                    # 流式处理特殊：边生边推。如果外部断了(buffer被清)，后台会在 yield 时察觉并清理退出
                    await _handle_generate_stream(task)
                    # done / error 状态由 _handle_generate_stream 内部负责标注
                    
                elif task_type == "theater_stream":
                    await _handle_theater_stream(task)
                    
                else:
                    raise ValueError(f"Unknown task type: {task_type}")
                    
            except Exception as e:
                if isinstance(e, RuntimeError) and 'cancelled' in str(e).lower():
                    # User-initiated cancellation, not a real error - mark as cancelled
                    job_statuses[task_id]["status"] = "cancelled"
                    print(f"⏹️ [任务取消] {meta_name} | 来自 {ip} | 用户在计算过程中主动取消")
                else:
                    traceback.print_exc()
                    job_statuses[task_id]["status"] = "error"
                    job_statuses[task_id]["error"] = str(e)
            finally:
                elapsed = time.time() - start_t
                mem = gpu_memory_report()
                if job_statuses.get(task_id, {}).get("status") == "error":
                    print(f"❌ [任务报错] {meta_name} | 来自 {ip} | 耗时 {elapsed:.1f}秒 | {mem}")
                elif job_statuses.get(task_id, {}).get("status") == "cancelled":
                    print(f"⏹️ [任务取消] {meta_name} | 来自 {ip} | 耗时 {elapsed:.1f}秒 | {mem}")
                else:
                    print(f"✅ [任务完成] {meta_name} | 来自 {ip} | 耗时 {elapsed:.1f}秒 | {mem}")
                
                # 清理工作
                job_queue.task_done()
                # 提示空闲
                if job_queue.empty():
                    print(f"💤 [服务器空闲] 当前无任务运行、无排队任务 | 在线设备: {device_tracker.get_online_count()} 台")
                
        except asyncio.CancelledError:
            print("⚠️ [后台守护进程] 接收到退出信号。")
            break
        except Exception as e:
            print(f"💀 [后台守护进程严重错误重启守护] {str(e)}")
            traceback.print_exc()
            await asyncio.sleep(1)


# ------- Background Worker Implementations -------

def _check_cancelled(task_id, profile_folder=None):
    """Check if user cancelled; if so, clean up and raise. Call between heavy computation steps."""
    if task_id and job_statuses.get(task_id, {}).get("status") == "cancelled":
        if profile_folder:
            shutil.rmtree(profile_folder, ignore_errors=True)
        raise RuntimeError("Task was cancelled by user")

async def _handle_extract_profile(task):
    profile_id = task["profile_id"]
    name = task.get("name_field", task.get("name", "未命名"))
    description = task.get("description", "")
    reference_text = task["reference_text"]
    task_id = task.get("task_id")
    
    profile_folder = PROFILES_DIR / profile_id
    source_audio_path = profile_folder / "source.wav"
    
    # Already saved source.wav and reference.txt by the endpoint handler
    prompt_1_7B = await engine.create_prompt(str(source_audio_path), reference_text, model_size="1.7B")
    prompt_1_7B_path = profile_folder / "prompt_1.7B.pt"
    torch.save(prompt_1_7B, prompt_1_7B_path)
    
    # ★ 早期取消探测点：1.7B 推理完毕，在启动 0.6B 之前立即检查
    _check_cancelled(task_id, profile_folder)
    
    prompt_0_6B = await engine.create_prompt(str(source_audio_path), reference_text, model_size="0.6B")
    prompt_0_6B_path = profile_folder / "prompt_0.6B.pt"
    torch.save(prompt_0_6B, prompt_0_6B_path)
    
    # ★ 写库前再次确认
    _check_cancelled(task_id, profile_folder)
    
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
    return dict(row)

async def _handle_transcribe(task):
    temp_file = task["temp_file"]
    language = task["language"]
    
    def _do_transcribe():
        return transcribe_engine.transcribe(str(temp_file), language)
        
    transcription = await asyncio.to_thread(_do_transcribe)
    
    if Path(temp_file).exists():
        Path(temp_file).unlink()
        
    return {"text": transcription}

async def _handle_generate(task):
    profile_id = task["profile_id"]
    text = task["text"]
    language = task["language"]
    model_size = task["model_size"]
    instruct = task.get("instruct")
    
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,))
    profile_row = c.fetchone()
    
    if not profile_row:
        conn.close()
        raise ValueError("数据库中找不到该音色配置")
        
    profile_folder = PROFILES_DIR / profile_id
    prompt_file = profile_folder / f"prompt_{model_size}.pt"
    
    if not prompt_file.exists():
        source_audio = profile_folder / "source.wav"
        ref_txt_file = profile_folder / "reference.txt"
        if not source_audio.exists() or not ref_txt_file.exists():
            conn.close()
            raise ValueError(f"缺少旧版原音频文件，无法为您重新生成 {model_size} 张量。")
        with open(ref_txt_file, "r", encoding="utf-8") as f:
            ref_text = f.read()
        prompt = await engine.create_prompt(str(source_audio), ref_text, model_size=model_size)
        torch.save(prompt, prompt_file)
    else:
        prompt = torch.load(prompt_file, weights_only=False)
    
    # ★ 推理前取消探测点
    _check_cancelled(task.get("task_id"))
    
    audio_array, sr = await engine.generate_speech(
        text=text, 
        voice_prompt=prompt, 
        language=language, 
        instruct=instruct,
        model_size=model_size
    )
    dur = len(audio_array) / sr
    
    # ★ 写库前取消探测点
    _check_cancelled(task.get("task_id"))
        
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

async def _handle_generate_stream(task):
    task_id = task["task_id"]
    profile_id = task["profile_id"]
    text = task["text"]
    language = task["language"]
    model_size = task["model_size"]
    instruct = task.get("instruct")
    
    q = stream_buffers.get(task_id)
    if not q:
        job_statuses[task_id]["status"] = "error"
        job_statuses[task_id]["error"] = "内部缓冲队列未找到"
        return

    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT * FROM profiles WHERE id=?", (profile_id,))
        profile_row = c.fetchone()
        
        if not profile_row:
            await q.put({"type": "error", "message": "数据库中找不到该音色配置"})
            job_statuses[task_id]["status"] = "error"
            job_statuses[task_id]["error"] = "Profile not found"
            conn.close()
            return
            
        profile_folder = PROFILES_DIR / profile_id
        prompt_file = profile_folder / f"prompt_{model_size}.pt"
        
        if not prompt_file.exists():
            source_audio = profile_folder / "source.wav"
            ref_txt_file = profile_folder / "reference.txt"
            if not source_audio.exists() or not ref_txt_file.exists():
                err_msg = "缺少原音频，无法重新推断该模型体积下的张量。"
                await q.put({"type": "error", "message": err_msg})
                job_statuses[task_id]["status"] = "error"
                job_statuses[task_id]["error"] = err_msg
                conn.close()
                return
            with open(ref_txt_file, "r", encoding="utf-8") as f:
                ref_text = f.read()
            prompt = await engine.create_prompt(str(source_audio), ref_text, model_size=model_size)
            torch.save(prompt, prompt_file)
        else:
            prompt = torch.load(prompt_file, weights_only=False)
        
        # 分句缓冲
        parts = re.split(r'(?<=[。！？；\n.!?;])', text)
        chunks = []
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if chunks and len(chunks[-1]) < 8:
                chunks[-1] += p
            else:
                chunks.append(p)
        if not chunks:
            chunks = [text]
            
        total_chunks = len(chunks)
        all_audio_arrays = []
        sample_rate = 24000
        
        await q.put({"type": "info", "total_chunks": total_chunks})
        
        for idx, chunk_text in enumerate(chunks):
            try:
                # 检查客户端是否还在等待，如果断开了我们就停止后续流的生成工作
                if task_id not in stream_buffers or job_statuses.get(task_id, {}).get("status") == "cancelled":
                    print(f"🛑 [流式中止] 客户端已断开或被取消，放弃后续推理。任务ID: {task_id[:8]}")
                    break
                    
                audio_array, sr = await engine.generate_speech(
                    text=chunk_text,
                    voice_prompt=prompt,
                    language=language,
                    instruct=instruct,
                    model_size=model_size
                )
                sample_rate = sr
                all_audio_arrays.append(audio_array)
                
                buf = io.BytesIO()
                sf.write(buf, audio_array, sr, format='WAV')
                buf.seek(0)
                audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                
                await q.put({"type": "chunk", "index": idx, "total": total_chunks, "audio_b64": audio_b64, "text": chunk_text})
                
            except Exception as chunk_err:
                traceback.print_exc()
                await q.put({"type": "chunk_error", "index": idx, "message": str(chunk_err)})
        
        # 保存完整历史 (如果生成了至少一段)
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
            
            await q.put({"type": "done", "history_id": gen_id, "duration": dur})
            
            # 记录到总库状态中
            job_statuses[task_id]["status"] = "done"
            c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id WHERE h.id=?", (gen_id,))
            job_statuses[task_id]["result"] = dict(c.fetchone())
            
        else:
            job_statuses[task_id]["status"] = "error"
            job_statuses[task_id]["error"] = "No chunks generated"
            await q.put({"type": "error", "message": "未能生成任何音频片段。"})
            
        conn.close()
        
    except Exception as e:
        traceback.print_exc()
        job_statuses[task_id]["status"] = "error"
        job_statuses[task_id]["error"] = str(e)
        if task_id in stream_buffers:
            await stream_buffers[task_id].put({"type": "error", "message": str(e)})

    finally:
        # 发送终结符(重要，让 HTTP 返回流跳出阻塞轮询)
        if task_id in stream_buffers:
            await stream_buffers[task_id].put(None)

async def _handle_theater_stream(task):
    task_id = task["task_id"]
    script_items = task["script_items"]
    language = task["language"]
    model_size = task["model_size"]
    
    q = stream_buffers.get(task_id)
    if not q:
        job_statuses[task_id]["status"] = "error"
        job_statuses[task_id]["error"] = "内部缓冲队列未找到"
        return
        
    try:
        # Load all needed prompts
        prompts = {}
        conn = get_db_connection()
        c = conn.cursor()
        for item in script_items:
            pid = item["profile_id"]
            if pid in prompts: continue
            
            c.execute("SELECT * FROM profiles WHERE id=?", (pid,))
            profile_row = c.fetchone()
            if not profile_row:
                raise ValueError(f"音色 {item['speaker_name']} 已被删除。")
                
            profile_folder = PROFILES_DIR / pid
            prompt_file = profile_folder / f"prompt_{model_size}.pt"
            
            if not prompt_file.exists():
                source_audio = profile_folder / "source.wav"
                ref_txt_file = profile_folder / "reference.txt"
                if not source_audio.exists() or not ref_txt_file.exists():
                    raise ValueError(f"缺少原音频，无法重新推断 {item['speaker_name']}。")
                with open(ref_txt_file, "r", encoding="utf-8") as f:
                    ref_text = f.read()
                prompt = await engine.create_prompt(str(source_audio), ref_text, model_size=model_size)
                torch.save(prompt, prompt_file)
            else:
                prompt = torch.load(prompt_file, weights_only=False)
            prompts[pid] = prompt
            
        # Prepare total chunks
        total_chunks = 0
        for item in script_items:
            parts = re.split(r'(?<=[。！？；\n.!?;])', item["text"])
            chunks = []
            for p in parts:
                p = p.strip()
                if not p: continue
                if chunks and len(chunks[-1]) < 8:
                    chunks[-1] += p
                else: chunks.append(p)
            if not chunks: chunks = [item["text"]]
            item["chunks"] = chunks
            total_chunks += len(chunks)
            
        await q.put({"type": "info", "total_chunks": total_chunks})
        
        all_audio_arrays = []
        sample_rate = 24000
        current_chunk_idx = 0
        
        for item in script_items:
            for chunk_text in item["chunks"]:
                if task_id not in stream_buffers or job_statuses.get(task_id, {}).get("status") == "cancelled":
                    print(f"🛑 [流式中止] 剧场客户端已断开...")
                    break
                    
                audio_array, sr = await engine.generate_speech(
                    text=chunk_text,
                    voice_prompt=prompts[item["profile_id"]],
                    language=language,
                    instruct=item["instruct"],
                    model_size=model_size
                )
                sample_rate = sr
                all_audio_arrays.append(audio_array)
                
                buf = io.BytesIO()
                sf.write(buf, audio_array, sr, format='WAV')
                buf.seek(0)
                audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                
                await q.put({"type": "chunk", "index": current_chunk_idx, "total": total_chunks, "audio_b64": audio_b64, "text": chunk_text})
                current_chunk_idx += 1
                
        # Save complete history
        if all_audio_arrays:
            full_audio = np.concatenate(all_audio_arrays)
            dur = len(full_audio) / sample_rate
            gen_id = str(uuid.uuid4())
            audio_file = HISTORY_DIR / f"{gen_id}.wav"
            sf.write(str(audio_file), full_audio, sample_rate)
            
            full_script_text = "\n\n".join([f"[{i['speaker_name']}]\n{i['text']}" for i in script_items])
            
            seen_speakers = set()
            speakers = []
            speaker_pids = []
            for i in script_items:
                if i["speaker_name"] not in seen_speakers:
                    seen_speakers.add(i["speaker_name"])
                    speakers.append(i["speaker_name"])
                    speaker_pids.append(i["profile_id"])
            
            speaker_names_str = "、".join(speakers)
            # Store all involved PIDs comma-separated for later lookup
            all_pids_str = ",".join(speaker_pids)
            
            c.execute(
                "INSERT INTO history (id, profile_id, text, language, instruct, audio_path, duration) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (gen_id, all_pids_str, "【小剧场】\n\n" + full_script_text, language, "小剧场演员：" + speaker_names_str, str(audio_file), dur)
            )
            conn.commit()
            
            await q.put({"type": "done", "history_id": gen_id, "duration": dur})
            job_statuses[task_id]["status"] = "done"
            c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id WHERE h.id=?", (gen_id,))
            job_statuses[task_id]["result"] = dict(c.fetchone())
        else:
            job_statuses[task_id]["status"] = "error"
            job_statuses[task_id]["error"] = "未能生成任何音频片段"
            await q.put({"type": "error", "message": "未能生成任何音频片段。"})
            
        conn.close()
            
    except Exception as e:
        traceback.print_exc()
        job_statuses[task_id]["status"] = "error"
        job_statuses[task_id]["error"] = str(e)
        if task_id in stream_buffers:
            await stream_buffers[task_id].put({"type": "error", "message": str(e)})

    finally:
        if task_id in stream_buffers:
            await stream_buffers[task_id].put(None)


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
    # 启动后台工作线程
    asyncio.create_task(bg_gpu_worker())
    
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
    gpu_mem = f"{torch.cuda.get_device_properties(0).total_memory / 1024**3:.0f}GB" if torch.cuda.is_available() else "N/A"
    
    total_freed_mb = (temp_freed_bytes + orphan_freed_bytes) / 1024 / 1024
    
    print("\n" + "=" * 55)
    print("    🎙️  Voicebox Qwen Web UI (个人主机版)")
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
    job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
    
    # Estimate it will be placed at the end of the queue
    sz = job_queue.qsize()
    return {"task_id": task_id, "position": sz + 1, "total": sz + 1}

@app.get("/api/queue_position/{task_id}")
async def queue_position(task_id: str):
    """Get the position and status of a specific task in the queue."""
    status_info = job_statuses.get(task_id)
    if not status_info:
        return {"task_id": task_id, "position": -1, "status": "unknown"}
        
    status = status_info["status"]
    if status in ["done", "error", "cancelled"]:
        return {"task_id": task_id, "position": -1, "status": status, "result": status_info.get("result"), "error": status_info.get("error")}
        
    if status == "processing":
        return {"task_id": task_id, "position": 0, "status": status}
        
    # Find exact position in the asyncio Queue, ignoring cancelled tasks
    position = -1
    valid_count = 0
    for t in job_queue._queue:
        tid = t.get("task_id")
        t_status = job_statuses.get(tid, {})
        if t_status.get("status") != "cancelled":
            valid_count += 1
            if tid == task_id:
                position = valid_count
                break
            
    if position == -1:
        # Request is registered but not yet put in the queue
        position = valid_count + 1
        
    return {"task_id": task_id, "position": position, "status": status}
    
@app.delete("/api/queue_cancel/{task_id}")
async def queue_cancel(task_id: str):
    """Client gave up waiting, mark as cancelled so worker can skip it."""
    if task_id in job_statuses and job_statuses[task_id]["status"] in ["queued", "processing"]:
        job_statuses[task_id]["status"] = "cancelled"
    return {"message": "cancelled"}

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
        job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
        
    profile_id = str(uuid.uuid4())
    profile_folder = PROFILES_DIR / profile_id
    profile_folder.mkdir(parents=True, exist_ok=True)
    
    source_audio_path = profile_folder / "source.wav"
    with open(source_audio_path, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)
        
    with open(profile_folder / "reference.txt", "w", encoding="utf-8") as f:
        f.write(reference_text)
        
    # 投递给后台 Worker
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    task = {
        "task_id": task_id,
        "type": "extract_profile",
        "name": "音色提取",
        "ip": client_ip,
        "profile_id": profile_id,
        "name_field": name,
        "description": description,
        "reference_text": reference_text
    }
    
    # 确保状态存在并修改为 queued
    if task_id not in job_statuses:
         job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
    
    await job_queue.put(task)
    
    # 因为此 API 原先是同步返回 ProfileResponse，为了少改前端代码，我们在这里阻塞等待后台完成这一个特殊的任务
    while True:
        status_info = job_statuses.get(task_id)
        if not status_info or status_info["status"] in ["done", "error", "cancelled"]:
            break
        await asyncio.sleep(0.5)
        
    if status_info["status"] == "error":
        raise HTTPException(status_code=500, detail=status_info.get("error"))
    if status_info["status"] == "cancelled":
        raise HTTPException(status_code=499, detail="Task was cancelled")
        
    return status_info["result"]

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
        job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
        
    temp_dir = Path("data/temp")
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_file = temp_dir / f"transcribe_{uuid.uuid4()}.wav"
    
    with open(temp_file, "wb") as buffer:
        shutil.copyfileobj(audio.file, buffer)
        
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    task = {
        "task_id": task_id,
        "type": "transcribe",
        "name": "语音听写",
        "ip": client_ip,
        "temp_file": str(temp_file),
        "language": language
    }
    
    if task_id not in job_statuses:
         job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
         
    await job_queue.put(task)
    
    # 阻塞等待结果
    while True:
        status_info = job_statuses.get(task_id)
        if not status_info or status_info["status"] in ["done", "error", "cancelled"]:
            break
        await asyncio.sleep(0.5)
        
    if status_info["status"] == "error":
        raise HTTPException(status_code=500, detail=status_info.get("error"))
    if status_info["status"] == "cancelled":
        raise HTTPException(status_code=499, detail="Task was cancelled")
        
    return status_info["result"]

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
        job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
        
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    task = {
        "task_id": task_id,
        "type": "generate",
        "name": "普通合成",
        "ip": client_ip,
        "profile_id": profile_id,
        "text": text,
        "language": language,
        "model_size": model_size,
        "instruct": instruct
    }
    
    if task_id not in job_statuses:
         job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
         
    await job_queue.put(task)
    
    # 阻塞等待结果
    while True:
        status_info = job_statuses.get(task_id)
        if not status_info or status_info["status"] in ["done", "error", "cancelled"]:
            break
        await asyncio.sleep(0.5)
        
    if status_info["status"] == "error":
        raise HTTPException(status_code=500, detail=status_info.get("error"))
    if status_info["status"] == "cancelled":
        raise HTTPException(status_code=499, detail="Task was cancelled")
        
    return status_info["result"]

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
        job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
        
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    
    # 建立独立缓冲队列并发布任务
    stream_buffers[task_id] = asyncio.Queue()
    
    task = {
        "task_id": task_id,
        "type": "generate_stream",
        "name": "流式合成",
        "ip": client_ip,
        "profile_id": profile_id,
        "text": text,
        "language": language,
        "model_size": model_size,
        "instruct": instruct
    }
    
    if task_id not in job_statuses:
         job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
         
    await job_queue.put(task)

    async def event_generator():
        try:
            # Emit queue events while waiting
            while True:
                status_info = job_statuses.get(task_id)
                if not status_info:
                    break
                    
                status = status_info["status"]
                
                # 如果被取消了 (比如前端放弃或者网络中断)，提前结束 (这里 HTTP 其实断了也会结束)
                if status == "cancelled":
                    break
                    
                # 轮询自身的位置，向前端发 queue 状态
                if status == "queued":
                    position = -1
                    valid_count = 0
                    for t in job_queue._queue:
                        tid = t.get("task_id")
                        t_status = job_statuses.get(tid, {})
                        if t_status.get("status") != "cancelled":
                            valid_count += 1
                            if tid == task_id:
                                position = valid_count
                                break
                                
                    if position == -1:
                        position = valid_count + 1
                        
                    yield f"data: {json.dumps({'type': 'queue', 'position': position})}\n\n"
                    await asyncio.sleep(1.0)
                    continue
                    
                if status in ["processing", "done", "error"]:
                    # 后端工作线程已开始拉取任务，可以跳出轮询了
                    yield f"data: {json.dumps({'type': 'queue', 'position': 0})}\n\n"
                    break
                    
            # 等待 Worker 写缓冲数据
            q = stream_buffers.get(task_id)
            if not q:
                return
                
            while True:
                msg = await q.get()
                if msg is None:  # EOF marking
                    break
                yield f"data: {json.dumps(msg)}\n\n"
                
                if msg.get("type") in ["done", "error"]:
                    break
                    
        except asyncio.CancelledError:
            # FastAPI 监测到 HTTP 断开
            print(f"⚠️ [API] 前端连接断开 (任务ID: {task_id[:8]})")
        finally:
            # 清理缓冲队列，工作线程看到它没了就不会再算后续的分句了
            if task_id in stream_buffers:
                del stream_buffers[task_id]
            # 如果还没开始就被抛弃，则通知工作线程跳过
            if task_id in job_statuses and job_statuses[task_id]["status"] == "queued":
                job_statuses[task_id]["status"] = "cancelled"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/theater_stream")
async def generate_theater_stream(
    request: Request,
    script: str = Form(...),
    language: str = Form("auto"),
    model_size: str = Form("1.7B"),
    task_id: str = Form(None)
):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id, name FROM profiles")
    profiles_map = {row["name"]: row["id"] for row in c.fetchall()}
    conn.close()

    lines = [line.strip() for line in script.split('\n')]
    segments = []
    current_name = None
    current_text = []
    
    for line in lines:
        if not line:
            if current_name and current_text:
                segments.append({"name": current_name, "content": "\n".join(current_text)})
                current_name = None
                current_text = []
            continue
            
        # If line exactly matches a known speaker name, it starts a new block
        if line in profiles_map:
            # Save previous block if exists
            if current_name and current_text:
                segments.append({"name": current_name, "content": "\n".join(current_text)})
            current_name = line
            current_text = []
        else:
            if current_name is None:
                # If we haven't found a valid name yet, and it's not a known speaker,
                # we just set it as the current_name (it will fail later with the 400 error letting user know)
                current_name = line
            else:
                current_text.append(line)
            
    if current_name and current_text:
        segments.append({"name": current_name, "content": "\n".join(current_text)})
        
    if not segments:
        raise HTTPException(status_code=400, detail="脚本格式不正确或为空，请参考示例。")
        
    parsed_items = []
    for seg in segments:
        name = seg["name"]
        content = seg["content"]
        
        if name not in profiles_map:
            raise HTTPException(status_code=400, detail=f"找不到名为 '{name}' 的音色，请检查剧本角色名。")
            
        profile_id = profiles_map[name]
        
        instruct = None
        if content and (content.startswith('(') or content.startswith('（')):
            idx1 = content.find(')')
            idx2 = content.find('）')
            idx = -1
            if idx1 != -1 and idx2 != -1:
                idx = min(idx1, idx2)
            elif idx1 != -1:
                idx = idx1
            elif idx2 != -1:
                idx = idx2
                
            if idx != -1:
                instruct = content[1:idx].strip()
                content = content[idx+1:].strip()
                
        if model_size == "0.6B":
            instruct = None
            
        parsed_items.append({
            "profile_id": profile_id,
            "text": content,
            "instruct": instruct,
            "speaker_name": name
        })
        
    if not task_id:
        task_id = str(uuid.uuid4())
        job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
        
    client_ip = request.client.host if hasattr(request, 'client') and request.client else "?"
    
    stream_buffers[task_id] = asyncio.Queue()
    
    task = {
        "task_id": task_id,
        "type": "theater_stream",
        "name": "小剧场连载",
        "ip": client_ip,
        "script_items": parsed_items,
        "language": language,
        "model_size": model_size
    }
    
    if task_id not in job_statuses:
         job_statuses[task_id] = {"status": "queued", "created_at": time.time(), "result": None, "error": None}
         
    await job_queue.put(task)

    async def event_generator():
        try:
            while True:
                status_info = job_statuses.get(task_id)
                if not status_info:
                    break
                    
                status = status_info["status"]
                
                if status == "cancelled":
                    break
                    
                if status == "queued":
                    position = -1
                    valid_count = 0
                    for t in job_queue._queue:
                        tid = t.get("task_id")
                        t_status = job_statuses.get(tid, {})
                        if t_status.get("status") != "cancelled":
                            valid_count += 1
                            if tid == task_id:
                                position = valid_count
                                break
                                
                    if position == -1:
                        position = valid_count + 1
                        
                    yield f"data: {json.dumps({'type': 'queue', 'position': position})}\n\n"
                    await asyncio.sleep(1.0)
                    continue
                    
                if status in ["processing", "done", "error"]:
                    yield f"data: {json.dumps({'type': 'queue', 'position': 0})}\n\n"
                    break
                    
            q = stream_buffers.get(task_id)
            if not q:
                return
                
            while True:
                msg = await q.get()
                if msg is None:
                    break
                yield f"data: {json.dumps(msg)}\n\n"
                
                if msg.get("type") in ["done", "error"]:
                    break
                    
        except asyncio.CancelledError:
            print(f"⚠️ [API] 前端连接断开 (任务ID: {task_id[:8]})")
        finally:
            if task_id in stream_buffers:
                del stream_buffers[task_id]
            if task_id in job_statuses and job_statuses[task_id]["status"] == "queued":
                job_statuses[task_id]["status"] = "cancelled"
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/queue_status")
async def queue_status():
    return {"tasks_in_queue": job_queue.qsize(), "is_active": len([k for k,v in job_statuses.items() if v.get("status") == "processing"]) > 0}

@app.get("/api/history", response_model=list[HistoryResponse])
async def list_history():
    conn = get_db_connection()
    c = conn.cursor()
    # Basic list
    c.execute("SELECT h.*, COALESCE(p.name, '已删除音色 (Deleted)') as profile_name FROM history h LEFT JOIN profiles p ON h.profile_id = p.id ORDER BY h.created_at DESC")
    rows = [dict(r) for r in c.fetchall()]
    
    # Enrich Theater items with detailed profile awareness
    cached_profiles = {}
    c.execute("SELECT id, name FROM profiles")
    for p in c.fetchall():
        cached_profiles[p["id"]] = p["name"]
    
    for row in rows:
        if row["text"] and row["text"].startswith("【小剧场】"):
            row["profile_name"] = "小剧场连载"
            # The profile_id column contains comma-separated IDs
            pids = row["profile_id"].split(",")
            # Reconstruct the "instruct" field with deleted labels
            # instruct format: "小剧场演员：Amor、Q、WJQ"
            if row["instruct"] and row["instruct"].startswith("小剧场演员："):
                raw_names_part = row["instruct"][len("小剧场演员："):]
                names = raw_names_part.split("、")
                
                new_names = []
                for idx, pid in enumerate(pids):
                    if idx < len(names):
                        orig_name = names[idx]
                        if pid not in cached_profiles:
                            new_names.append(f"{orig_name}(已删除)")
                        else:
                            new_names.append(orig_name)
                    else:
                        # Fallback for unexpected mismatch
                        if pid not in cached_profiles:
                            new_names.append("佚名(已删除)")
                        else:
                            new_names.append(cached_profiles[pid])
                            
                row["instruct"] = "小剧场演员：" + "、".join(new_names)

    conn.close()
    return rows

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

