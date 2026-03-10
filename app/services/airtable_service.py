from datetime import datetime
from typing import Optional

import structlog
from pyairtable import Api
from pyairtable.formulas import match

from app.config import get_settings
from app.models.schemas import InteractionRecord, ResolutionStatus

logger = structlog.get_logger(__name__)


class AirtableService:
    def __init__(self) -> None:
        settings = get_settings()
        api = Api(settings.airtable_api_key)
        self._table = api.table(settings.airtable_base_id, settings.airtable_table_name)

    async def create_interaction(self, record: InteractionRecord) -> Optional[str]:
        """Create a new interaction record. Returns the Airtable record ID."""
        try:
            fields = {
                "caller_number": record.caller_number,
                "created_at": record.start_time.strftime("%Y-%m-%d"),
            }
            result = self._table.create(fields)
            logger.info(
                "airtable.interaction_created",
                call_sid=record.call_sid,
                airtable_id=result["id"],
            )
            return result["id"]
        except Exception as exc:
            logger.error(
                "airtable.create_failed",
                call_sid=record.call_sid,
                error=str(exc),
            )
            return None

    async def update_interaction(
        self,
        airtable_id: str,
        *,
        end_time: Optional[datetime] = None,
        duration_seconds: Optional[int] = None,
        transcript: Optional[str] = None,
        intent: Optional[str] = None,
        resolution_status: Optional[ResolutionStatus] = None,
        agent_notes: Optional[str] = None,
        caller_name: Optional[str] = None,
    ) -> bool:
        """Patch an existing interaction record with final call data."""
        try:
            fields: dict = {}
            if duration_seconds is not None:
                fields["duration_seconds"] = duration_seconds
            if transcript:
                fields["transcript"] = transcript[:100_000]  # Airtable field limit

            if fields:
                self._table.update(airtable_id, fields)
                logger.info("airtable.interaction_updated", airtable_id=airtable_id)
            return True
        except Exception as exc:
            logger.error(
                "airtable.update_failed",
                airtable_id=airtable_id,
                error=str(exc),
            )
            return False

    async def find_by_call_sid(self, call_sid: str) -> Optional[dict]:
        """Return the first Airtable record matching the given Twilio CallSID."""
        try:
            formula = match({"caller_number": call_sid})
            records = self._table.all(formula=formula)
            return records[0] if records else None
        except Exception as exc:
            logger.error(
                "airtable.find_failed",
                call_sid=call_sid,
                error=str(exc),
            )
            return None
