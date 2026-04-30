import requests
from app.config import settings


class OllamaConnectionError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL

    def generate(self, prompt: str, model: str = None) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            response = requests.post(url, json=payload, timeout=120)
            response.raise_for_status()
            return response.json()["response"]
        except requests.ConnectionError as e:
            raise OllamaConnectionError(f"Cannot reach Ollama at {self.base_url}: {e}") from e
        except requests.Timeout as e:
            raise OllamaConnectionError(f"Ollama request timed out: {e}") from e
