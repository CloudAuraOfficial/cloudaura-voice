import asyncio
from datetime import datetime, timezone
from typing import Optional

import structlog
from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, elevenlabs, openai, silero

from app.config import get_settings
from app.logging_config import configure_logging
from app.models.schemas import InteractionRecord, ResolutionStatus
from app.prompts.system_prompt import GREETING_MESSAGE, PERSONAL_AGENT_PROMPT
from app.services.airtable_service import AirtableService

logger = structlog.get_logger(__name__)


class CallSession:
    """Holds mutable state for a single inbound call."""

    def __init__(self, call_sid: str, caller_number: str, room_name: str) -> None:
        self.call_sid = call_sid
        self.caller_number = caller_number
        self.room_name = room_name
        self.start_time = datetime.now(timezone.utc)
        self.transcript_parts: list[str] = []
        self.caller_name: Optional[str] = None
        self.detected_intent: Optional[str] = None
        self.resolution_status = ResolutionStatus.DROPPED
        self.airtable_id: Optional[str] = None


async def entrypoint(ctx: JobContext) -> None:
    """
    LiveKit agent entrypoint — called once per dispatched room.

    Room naming convention (set by Twilio webhook):
        call_{twilio_call_sid}_{caller_e164_with_dashes}
    e.g.: call_CA1234abcd_-15559990000
    """
    settings = get_settings()
    log = logger.bind(room=ctx.room.name)

    # Parse call metadata from room name
    parts = ctx.room.name.split("_", 2)
    call_sid = parts[1] if len(parts) > 1 else ctx.room.name
    caller_number = parts[2].replace("-", "+") if len(parts) > 2 else "unknown"

    session = CallSession(
        call_sid=call_sid,
        caller_number=caller_number,
        room_name=ctx.room.name,
    )

    # Open Airtable record immediately so the call is always tracked
    airtable = AirtableService()
    record = InteractionRecord(
        call_sid=session.call_sid,
        caller_number=session.caller_number,
        room_name=session.room_name,
    )
    session.airtable_id = await airtable.create_interaction(record)

    # System prompt context
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=PERSONAL_AGENT_PROMPT,
    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    log.info("agent.room_connected")

    agent = VoicePipelineAgent(
        vad=silero.VAD.load(),
        stt=deepgram.STT(
            model="nova-2-phonecall",
            language="en-US",
            punctuate=True,
            interim_results=True,
        ),
        llm=openai.LLM(
            model=settings.openai_model,
            temperature=0.4,
        ),
        tts=elevenlabs.TTS(
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model_id,
            api_key=settings.elevenlabs_api_key,
        ),
        chat_ctx=initial_ctx,
        allow_interruptions=True,
        interrupt_speech_duration=0.6,
        min_endpointing_delay=0.5,
    )

    @agent.on("user_speech_committed")
    def on_user_speech(msg: llm.ChatMessage) -> None:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        session.transcript_parts.append(f"Caller: {content}")
        log.debug("agent.user_speech", preview=content[:80])

    @agent.on("agent_speech_committed")
    def on_agent_speech(msg: llm.ChatMessage) -> None:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        session.transcript_parts.append(f"Aura: {content}")
        log.debug("agent.aura_speech", preview=content[:80])

    agent.start(ctx.room)
    log.info("agent.pipeline_started")

    # Open the conversation
    await agent.say(GREETING_MESSAGE, allow_interruptions=True)

    try:
        await ctx.wait_for_disconnect()
    finally:
        await _close_session(session, airtable, log)


async def _close_session(
    session: CallSession,
    airtable: AirtableService,
    log,
) -> None:
    """Persist final transcript and metadata to Airtable."""
    end_time = datetime.now(timezone.utc)
    duration = int((end_time - session.start_time).total_seconds())
    transcript = "\n".join(session.transcript_parts)

    log.info(
        "agent.session_closed",
        duration_seconds=duration,
        turns=len(session.transcript_parts),
        resolution=session.resolution_status.value,
    )

    if session.airtable_id:
        await airtable.update_interaction(
            session.airtable_id,
            end_time=end_time,
            duration_seconds=duration,
            transcript=transcript,
            intent=session.detected_intent,
            resolution_status=session.resolution_status,
            caller_name=session.caller_name,
        )


def run_worker() -> None:
    """Start the LiveKit agent worker process."""
    settings = get_settings()
    configure_logging(settings.log_level)

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            api_key=settings.livekit_api_key,
            api_secret=settings.livekit_api_secret,
            ws_url=settings.livekit_url,
        )
    )


if __name__ == "__main__":
    run_worker()
