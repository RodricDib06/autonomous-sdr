import time
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from app.database import crud


class BaseAgent(ABC):
    name: str = "base_agent"

    @abstractmethod
    def run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        """Execute the agent. Must return a result dict."""

    def _log(
        self,
        db: Session,
        lead_id: str,
        input_data: dict,
        output_data: dict | None,
        duration_ms: int,
        success: bool,
        error: str | None = None,
    ) -> None:
        crud.create_agent_log(
            db=db,
            lead_id=lead_id,
            agent_name=self.name,
            input_data=input_data,
            output_data=output_data,
            duration_ms=duration_ms,
            success=success,
            error_message=error,
        )

    def _timed_run(self, db: Session, lead_id: str, input_data: dict) -> dict:
        start = time.time()
        try:
            result = self.run(db, lead_id, input_data)
            duration_ms = int((time.time() - start) * 1000)
            self._log(db, lead_id, input_data, result, duration_ms, success=True)
            return result
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            self._log(db, lead_id, input_data, None, duration_ms, success=False, error=str(e))
            raise
