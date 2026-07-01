import asyncio
import aiohttp
import requests
from app.config import settings


class OllamaConnectionError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.model = model or settings.OLLAMA_MODEL

    def generate(self, prompt: str, model: str = None) -> str:
        """Synchronous generate method for backward compatibility"""
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

    async def generate_async(self, prompt: str, model: str = None) -> str:
        """Async generate method"""
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model or self.model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as response:
                    response.raise_for_status()
                    result = await response.json()
                    return result["response"]
        except aiohttp.ClientError as e:
            raise OllamaConnectionError(f"Cannot reach Ollama at {self.base_url}: {e}") from e

    async def generate_batch(self, prompts: list[str], model: str = None) -> list[str]:
        """Generate responses for multiple prompts concurrently"""
        tasks = [self.generate_async(prompt, model) for prompt in prompts]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_generate(self, prompt: str, model: str = None):
        """Async generator that yields text tokens as they are produced by Ollama."""
        import json as _json
        url = f"{self.base_url}/api/generate"
        payload = {"model": model or self.model, "prompt": prompt, "stream": True}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=120)) as resp:
                resp.raise_for_status()
                async for line in resp.content:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = _json.loads(line)
                        token = chunk.get("response", "")
                        if token:
                            yield token
                        if chunk.get("done"):
                            break
                    except Exception:
                        continue
