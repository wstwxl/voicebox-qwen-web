from pydantic import BaseModel
from typing import Optional, List

class BatchDownloadRequest(BaseModel):
    ids: List[str]

class ProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ProfileResponse(BaseModel):
    id: str
    name: str
    description: Optional[str]
    created_at: str
    owner: str = "amorwest"
    is_default: int = 0

class GenerationRequest(BaseModel):
    profile_id: str
    text: str
    language: str = "zh"
    instruct: Optional[str] = None

class HistoryResponse(BaseModel):
    id: str
    profile_id: str
    profile_name: str
    text: str
    language: str
    audio_path: str
    created_at: str
    duration: float
    instruct: Optional[str]
    username: str = "amorwest"
