const API_BASE = '/api';

// Elements
const profileList = document.getElementById('profileList');
const profileCount = document.getElementById('profileCount');
const selProfile = document.getElementById('selProfile');
const historyList = document.getElementById('historyList');

// App State
let profiles = [];
let histories = [];

// Init
window.onload = () => {
    loadProfiles();
    loadHistory();
}

// ---------------- UI Helpers ----------------
function showLoader(text) {
    document.getElementById('loaderText').innerText = text || "正在处理...";
    document.getElementById('loader').style.display = 'flex';
}
function hideLoader() {
    document.getElementById('loader').style.display = 'none';
}

function toast(msg) {
    alert(msg); // simple fallback
}

// ---------------- Profiles ----------------
async function loadProfiles() {
    try {
        const res = await fetch(`${API_BASE}/profiles`);
        profiles = await res.json();

        profileCount.innerText = profiles.length;

        // Render List
        if (profiles.length === 0) {
            profileList.innerHTML = '<div class="text-center text-sm text-gray-500 py-4">尚未提取音色，马上录一个吧！</div>';
        } else {
            profileList.innerHTML = profiles.map(p => `
                <div class="flex items-center justify-between p-3 rounded-xl bg-card border border-slate-700/50 hover:border-brand/30 transition-colors group">
                    <div class="flex items-center space-x-3 truncate">
                        <div class="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-brand font-bold text-xs ring-2 ring-brand/20">${p.name.charAt(0)}</div>
                        <div class="truncate">
                            <h4 class="text-sm font-medium text-gray-200 truncate">${p.name}</h4>
                            <p class="text-[10px] text-gray-400 truncate">${p.created_at.split('.')[0]}</p>
                        </div>
                    </div>
                    
                    <div class="flex items-center space-x-2">
                        <button id="play-btn-${p.id}" onclick="toggleProfileAudio('${p.id}')" class="p-1.5" title="试听/停止原声">
                            <svg class="w-4 h-4 text-gray-400 group-hover:text-brand transition-colors" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"></path></svg>
                        </button>
                        <button onclick="deleteProfile('${p.id}')" class="text-gray-500 hover:text-rose-500 p-1.5 opacity-0 group-hover:opacity-100 transition-opacity" title="删除">
                            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                        </button>
                    </div>
                </div>
            `).join('');
        }

        // Render Dropdown
        selProfile.innerHTML = '<option value="" disabled selected>-- 请选择用来合成发声的音色 --</option>' +
            profiles.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

    } catch (e) {
        console.error(e);
        profileList.innerHTML = '<div class="text-rose-400 text-sm text-center">加载失败</div>';
    }
}

// ---------------- Profile Audio Playback ----------------
let currentPlayingProfileAudio = null;
let currentPlayingProfileId = null;

function toggleProfileAudio(profileId) {
    if (currentPlayingProfileAudio && currentPlayingProfileId === profileId) {
        // Stop current
        currentPlayingProfileAudio.pause();
        currentPlayingProfileAudio.currentTime = 0;
        currentPlayingProfileAudio = null;
        currentPlayingProfileId = null;
        updateProfilePlayButton(profileId, false);
        return;
    }

    // Stop any existing
    if (currentPlayingProfileAudio) {
        currentPlayingProfileAudio.pause();
        currentPlayingProfileAudio.currentTime = 0;
        const oldId = currentPlayingProfileId;
        currentPlayingProfileAudio = null;
        currentPlayingProfileId = null;
        if (oldId) updateProfilePlayButton(oldId, false);
    }

    // Play new
    const audio = new Audio(`${API_BASE}/../audio/profiles/${profileId}`);
    audio.play().catch(e => {
        alert('无法播放该音色的原声。可能是旧版本直接迁移导致母带音频已丢失。');
        updateProfilePlayButton(profileId, false);
    });

    currentPlayingProfileAudio = audio;
    currentPlayingProfileId = profileId;
    updateProfilePlayButton(profileId, true);

    audio.onended = () => {
        if (currentPlayingProfileId === profileId) {
            currentPlayingProfileAudio = null;
            currentPlayingProfileId = null;
            updateProfilePlayButton(profileId, false);
        }
    };
}

function updateProfilePlayButton(profileId, isPlaying) {
    const btn = document.getElementById(`play-btn-${profileId}`);
    if (!btn) return;
    if (isPlaying) {
        // Stop icon
        btn.innerHTML = `<svg class="w-4 h-4 text-brand" fill="currentColor" viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"></path></svg>`;
    } else {
        // Play icon
        btn.innerHTML = `<svg class="w-4 h-4 text-gray-400 group-hover:text-brand transition-colors" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"></path></svg>`;
    }
}

async function deleteProfile(id) {
    if (!confirm('确定删除此音色特征吗？')) return;
    try {
        await fetch(`${API_BASE}/profiles/${id}`, { method: 'DELETE' });
        loadProfiles();
        loadHistory();
    } catch (e) {
        alert('删除失败');
    }
}

// ---------------- Add Profile (Upload/Record) ----------------
function validateProfileInput() {
    const name = document.getElementById('newProfileName').value.trim();
    const text = document.getElementById('newProfileRefText').value.trim();
    if (!name || !text) {
        alert("请输入「音色命名」和「参考文本」！这对于 Qwen3 提取基因至关重要。");
        return false;
    }
    return { name, text };
}

async function uploadAudioBlob(blob, filename) {
    const input = validateProfileInput();
    if (!input) return;

    const formData = new FormData();
    formData.append('audio', blob, filename);
    formData.append('name', input.name);
    formData.append('reference_text', input.text);
    formData.append('description', 'Local Studio UI created');

    showLoader("正在发送给 GPU 分析提取声音特征 (1024/2048维张量) ...");

    try {
        const res = await fetch(`${API_BASE}/profiles`, {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error(await res.text());

        // Reset form
        document.getElementById('newProfileName').value = '';
        document.getElementById('newProfileRefText').value = '';
        discardStagedAudio();

        await loadProfiles();
        alert('音色提取完成并已持久化保存！');
    } catch (e) {
        console.error(e);
        alert('提取失败: ' + e.message);
    } finally {
        hideLoader();
    }
}

// ------ Audio Blob to WAV Converter (To bypass backend ffmpeg requirement) ------
async function convertToWav(audioBlob) {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const arrayBuffer = await audioBlob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    // Convert to WAV
    const numberOfChannels = audioBuffer.numberOfChannels;
    const sampleRate = audioBuffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numberOfChannels * bytesPerSample;

    // Interleave channels
    const length = audioBuffer.length;
    const interleaved = new Float32Array(length * numberOfChannels);
    for (let channel = 0; channel < numberOfChannels; channel++) {
        const channelData = audioBuffer.getChannelData(channel);
        for (let i = 0; i < length; i++) {
            interleaved[i * numberOfChannels + channel] = channelData[i];
        }
    }

    const dataLength = interleaved.length * bytesPerSample;
    const buffer2 = new ArrayBuffer(44 + dataLength);
    const view = new DataView(buffer2);

    function writeString(v, offset, string) {
        for (let i = 0; i < string.length; i++) {
            v.setUint8(offset + i, string.charCodeAt(i));
        }
    }

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numberOfChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(view, 36, 'data');
    view.setUint32(40, dataLength, true);

    let offset = 44;
    for (let i = 0; i < interleaved.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, interleaved[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }

    await audioContext.close();
    return new Blob([buffer2], { type: 'audio/wav' });
}

async function handleFileUpload(e) {
    const file = e.target.files[0];
    if (!file) return;
    e.target.value = ''; // reset
    showLoader("正在将音频格式转码为16-bit PCM WAV...");
    try {
        const cleanWav = await convertToWav(file);
        stageAudioBlob(cleanWav, file.name.replace(/\.[^/.]+$/, "") + ".wav");
    } catch (err) {
        console.error(err);
        alert("音频解析失败，请尝试其他格式: " + err.message);
    } finally {
        hideLoader();
    }
}

// ------ Audio Staging (Two-step Creation) ------
let stagedBlob = null;
let stagedFilename = null;

function stageAudioBlob(blob, filename) {
    stagedBlob = blob;
    stagedFilename = filename;
    document.getElementById('stagedAudioPlayer').src = URL.createObjectURL(blob);
    document.getElementById('step1Audio').classList.add('hidden');
    document.getElementById('step2Form').classList.remove('hidden');
}

function discardStagedAudio() {
    stagedBlob = null;
    stagedFilename = null;
    document.getElementById('stagedAudioPlayer').src = '';
    document.getElementById('step1Audio').classList.remove('hidden');
    document.getElementById('step2Form').classList.add('hidden');
}

async function transcribeStagedAudio() {
    if (!stagedBlob) return alert("没有供听写的音频数据！");

    const lang = document.getElementById('selTranscribeLang').value;
    const btn = document.getElementById('btnTranscribe');
    const originalText = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = `<span class="w-4 h-4 mr-2 border-2 border-indigo-300 border-t-transparent rounded-full animate-spin"></span> 正在识别...`;

    try {
        const formData = new FormData();
        formData.append('audio', stagedBlob, stagedFilename);
        formData.append('language', lang);

        const res = await fetch(`${API_BASE}/transcribe`, {
            method: 'POST',
            body: formData
        });

        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        document.getElementById('newProfileRefText').value = data.text;
    } catch (e) {
        console.error(e);
        alert('听写失败: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

async function submitNewProfile() {
    if (!stagedBlob) return alert("没有供上传的音频数据！");
    uploadAudioBlob(stagedBlob, stagedFilename);
}

// ------ Audio Recorders ------
let mediaRecorder;
let audioChunks = [];
let isRecordingMic = false;
let isRecordingSys = false;

function uiStartRec(typeText) {
    document.getElementById('recordingStatus').classList.remove('hidden');
    document.getElementById('recordingText').innerText = `正在录制: ${typeText}`;
}
function uiStopRec() {
    document.getElementById('recordingStatus').classList.add('hidden');
}

async function startRecording(recordStream, typeName, originalStreamToStop = null) {
    audioChunks = [];
    mediaRecorder = new MediaRecorder(recordStream);
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) audioChunks.push(e.data); };
    mediaRecorder.onstop = async () => {
        if (originalStreamToStop) {
            originalStreamToStop.getTracks().forEach(track => track.stop());
        } else {
            recordStream.getTracks().forEach(track => track.stop());
        }
        uiStopRec();
        const rawBlob = new Blob(audioChunks);
        showLoader("正在处理录音文件格式...");
        try {
            const cleanWav = await convertToWav(rawBlob);
            stageAudioBlob(cleanWav, `record_${Date.now()}.wav`);
        } catch (err) {
            console.error(err);
            alert("录音处理失败: " + err.message);
        } finally {
            hideLoader();
        }
    };
    mediaRecorder.start();
    uiStartRec(typeName);
}

async function toggleMicRecording() {

    if (isRecordingMic) {
        // Stop
        mediaRecorder.stop();
        isRecordingMic = false;
        document.getElementById('btnRecMic').classList.remove('bg-rose-500/20', 'border-rose-500/50');
    } else {
        // Start
        try {
            const stream = await navigator.mediaDevices.getUserMedia({
                audio: { autoGainControl: false, echoCancellation: false, noiseSuppression: false }
            });
            startRecording(stream, "麦克风");
            isRecordingMic = true;
            document.getElementById('btnRecMic').classList.add('bg-rose-500/20', 'border-rose-500/50');
        } catch (e) {
            alert('无法访问麦克风: ' + e.message);
        }
    }
}

async function toggleSysRecording() {

    if (isRecordingSys) {
        mediaRecorder.stop();
        isRecordingSys = false;
        document.getElementById('btnRecSys').classList.remove('bg-accent/20', 'border-accent/50');
        document.getElementById('sysRecHelp').classList.add('hidden');
    } else {
        try {
            document.getElementById('sysRecHelp').classList.remove('hidden');
            const stream = await navigator.mediaDevices.getDisplayMedia({
                video: { frameRate: { ideal: 1, max: 2 } }, // Minimize video capturing overhead
                audio: { autoGainControl: false, echoCancellation: false, noiseSuppression: false }
            });

            // Check if audio track exists
            const audioTracks = stream.getAudioTracks();
            if (audioTracks.length === 0) {
                stream.getTracks().forEach(t => t.stop());
                alert('未检测到音频轨道！请在分享屏幕时务必勾选"分享音频"选项。');
                document.getElementById('sysRecHelp').classList.add('hidden');
                return;
            }

            // Only keep audio
            const audioStream = new MediaStream([audioTracks[0]]);

            // Also stop recording if user clicks "Stop sharing" in browser UI
            audioStream.getTracks()[0].onended = () => {
                if (isRecordingSys) {
                    toggleSysRecording();
                }
            };

            startRecording(audioStream, "系统内录", stream);
            isRecordingSys = true;
            document.getElementById('btnRecSys').classList.add('bg-accent/20', 'border-accent/50');
        } catch (e) {
            document.getElementById('sysRecHelp').classList.add('hidden');
            if (e.name !== 'NotAllowedError') {
                alert('系统录制失败: ' + e.message);
            }
        }
    }
}


// ---------------- Generation ----------------

async function generateTTS() {
    const profile_id = selProfile.value;
    const model_size = document.getElementById('selModel').value;
    const language = document.getElementById('selTTSLang').value;
    const text = document.getElementById('inpText').value.trim();
    const instruct = document.getElementById('inpInstruct').value.trim();

    if (!profile_id) return alert('请先选择一个提取好的音色！');
    if (!text) return alert('请输入要合成的文本！');
    if (model_size === '0.6B' && instruct) {
        // the user's instructions will be ignored by backend, so we warn them here or just clear it.
        alert('温馨提示：0.6B 极速模型在架构上不支持情感变调（Delivery Instructions）。我们将清除此选项进行生成。');
        document.getElementById('inpInstruct').value = '';
    }

    const formData = new FormData();
    formData.append('profile_id', profile_id);
    formData.append('model_size', model_size);
    formData.append('language', language);
    formData.append('text', text);
    if (document.getElementById('inpInstruct').value.trim()) {
        formData.append('instruct', document.getElementById('inpInstruct').value.trim());
    }

    showLoader("RTX 4060 大模型推理中，加载 Qwen3-TTS 权重...");
    document.getElementById('btnGenerate').disabled = true;

    try {
        const res = await fetch(`${API_BASE}/generate`, {
            method: 'POST',
            body: formData
        });
        if (!res.ok) throw new Error(await res.text());

        await loadHistory();
    } catch (e) {
        console.error(e);
        alert('生成失败: ' + e.message);
    } finally {
        hideLoader();
        document.getElementById('btnGenerate').disabled = false;
    }
}

// ---------------- History & Download ----------------

async function loadHistory() {
    try {
        const res = await fetch(`${API_BASE}/history`);
        histories = await res.json();

        if (histories.length === 0) {
            historyList.innerHTML = '<div class="text-center text-sm text-gray-500 py-4">暂无生成记录</div>';
            return;
        }

        historyList.innerHTML = histories.map(h => {
            const timeStr = h.created_at.replace('T', ' ').split('.')[0];
            const instructBadge = h.instruct ? `<span class="bg-accent/20 text-accent text-[10px] px-2 py-0.5 rounded ml-2 border border-accent/30 font-semibold" title="情绪提示词">"${h.instruct}"</span>` : '';

            return `
            <div class="p-4 rounded-xl bg-card border border-slate-700 hover:border-brand/40 transition-colors shadow-sm group">
                <div class="flex items-start mb-2">
                    <input type="checkbox" class="hist-checkbox mt-1 mr-3 w-4 h-4 rounded border-gray-600 text-brand focus:ring-brand bg-slate-800" value="${h.id}" data-filename="${h.profile_name}-${h.language}-${h.duration.toFixed(1)}s.wav">
                    <div class="flex-grow">
                        <div class="flex items-center justify-between mb-1">
                            <div class="flex items-center">
                                <span class="bg-indigo-900/50 text-indigo-300 text-[10px] px-2 py-0.5 rounded border border-indigo-700/50 font-medium">${h.profile_name}</span>
                                ${instructBadge}
                            </div>
                            <span class="text-[10px] text-gray-500">${timeStr} (${h.duration.toFixed(1)}s)</span>
                        </div>
                        <p class="text-sm text-gray-300 leading-relaxed mb-3">${h.text}</p>
                        
                        <!-- 底部控制栏 -->
                        <div class="flex items-center justify-between bg-dark/50 rounded-lg p-2 border border-slate-700/50">
                            <!-- 浏览器原生暗黑播放器 -->
                            <audio controls src="/audio/history/${h.id}" class="h-8 max-w-[200px] md:max-w-xs scale-90 origin-left brightness-90 contrast-125 sepia-0 hue-rotate-180 invert"></audio>
                            
                            <div class="flex space-x-1">
                                <button onclick="downloadSingle('${h.id}')" class="p-1.5 text-gray-400 hover:text-brand hover:bg-brand/10 rounded transition-colors" title="下载WAV">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                                </button>
                                <button onclick="deleteHistory('${h.id}')" class="p-1.5 text-gray-500 hover:text-rose-500 hover:bg-rose-500/10 rounded transition-colors" title="删除">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
        }).join('');

    } catch (e) {
        console.error(e);
        historyList.innerHTML = '<div class="text-rose-400 text-sm py-4">加载历史记录失败</div>';
    }
}

async function deleteHistory(id) {
    if (!confirm('确定删除此条记录及其音频文件？')) return;
    try {
        await fetch(`${API_BASE}/history/${id}`, { method: 'DELETE' });
        loadHistory();
    } catch (e) { alert('删除失败'); }
}

function downloadSingle(id) {
    const a = document.createElement('a');
    a.href = `/audio/history/${id}`;
    // It will auto download because browser handles attachment disposition
    a.click();
}

async function downloadSelected() {
    const checkboxes = document.querySelectorAll('.hist-checkbox:checked');
    if (checkboxes.length === 0) {
        alert("请在左侧多选框中勾选需要下载的记录");
        return;
    }

    const ids = Array.from(checkboxes).map(cb => cb.value);

    showLoader("正在为您连云打包所选项为 ZIP ...");
    try {
        const res = await fetch(`${API_BASE}/history/batch_download`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ids })
        });

        if (!res.ok) throw new Error(await res.text());

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = "voicebox_batch_download.zip";
        document.body.appendChild(a);
        a.click();

        window.URL.revokeObjectURL(url);
        a.remove();

        // Uncheck all after download
        checkboxes.forEach(cb => cb.checked = false);
    } catch (err) {
        console.error(err);
        alert("批量下载失败: " + err.message);
    } finally {
        hideLoader();
    }
}
