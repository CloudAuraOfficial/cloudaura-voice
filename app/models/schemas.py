from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class CallStatus(str, Enum):
    INITIATED = "initiated"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_ANSWER = "no_answer"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CALLBACK_REQUESTED = "callback_requested"
    DROPPED = "dropped"


class InteractionRecord(BaseModel):
    call_sid: str
    caller_number: str
    caller_name: Optional[str] = None
    room_name: str
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    transcript: Optional[str] = None
    intent: Optional[str] = None
    resolution_status: ResolutionStatus = ResolutionStatus.DROPPED
    agent_notes: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    environment: str
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
