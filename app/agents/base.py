import json
import re
import time
from abc import ABC, abstractmethod
from sqlalchemy.orm import Session
from app.database import crud


class BaseAgent(ABC):
    name: str = "base_agent"

    def _parse_json(self, text: str) -> dict:
        """Robust JSON extractor that survives Ollama's occasional bad output."""
        # Strip markdown code fences
        text = re.sub(r"```(?:json)?\s*", "", text).strip()

        # Find the outermost JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError(f"No JSON object found in LLM response: {text[:200]}")

        raw = match.group()

        # Attempt 1: parse as-is
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Attempt 2: strip ASCII control characters (0x00-0x1F except tab/newline)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 3: collapse literal newlines inside string values
        cleaned = re.sub(r'(?<=\S)\n(?=\S)', ' ', cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Attempt 4: extract individual key-value pairs via regex as last resort
        result: dict = {}
        for key, val in re.findall(r'"(\w+)"\s*:\s*"([^"]*)"', cleaned):
            result[key] = val
        for key, val in re.findall(r'"(\w+)"\s*:\s*(true|false|[\d.]+)', cleaned):
            if val == "true":
                result[key] = True
            elif val == "false":
                result[key] = False
            else:
                result[key] = float(val) if "." in val else int(val)

        if result:
            return result

        raise ValueError(f"Could not parse JSON from LLM response: {text[:300]}")

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
