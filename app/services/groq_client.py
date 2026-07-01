import logging
from app.config import settings

log = logging.getLogger(__name__)


class GroqClient:
    """
    Groq inference client — drop-in replacement for OllamaClient.

    Uses llama-3.1-70b-versatile by default (~500 tok/s, free tier:
    6 000 req/h, 500 000 tok/min). Sign up at https://console.groq.com.

    # PRODUCTION: swap model for groq/llama-3.3-70b-specdec for even higher
    # throughput, or mixtral-8x7b-32768 for longer context windows.
    """

    def __init__(self):
        try:
            from groq import Groq
            self._client = Groq(api_key=settings.GROQ_API_KEY)
        except ImportError as e:
            raise RuntimeError("groq package not installed — run: pip install groq") from e
        self.model = settings.GROQ_MODEL

    def generate(self, prompt: str, model: str = None) -> str:
        """Synchronous generate — mirrors OllamaClient.generate signature."""
        response = self._client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=2048,
        )
        return response.choices[0].message.content

    async def generate_async(self, prompt: str, model: str = None) -> str:
        """Async generate — runs sync Groq call in threadpool to avoid blocking."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, prompt, model)

    async def generate_batch(self, prompts: list[str], model: str = None) -> list[str]:
        import asyncio
        tasks = [self.generate_async(p, model) for p in prompts]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def stream_generate(self, prompt: str, model: str = None):
        """Async generator that yields text tokens from Groq's streaming API."""
        import asyncio
        loop = asyncio.get_event_loop()

        def _iter_chunks():
            stream = self._client.chat.completions.create(
                model=model or self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2048,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        # Run the blocking iterator in a thread pool and yield tokens
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def _producer():
            try:
                for token in _iter_chunks():
                    loop.call_soon_threadsafe(queue.put_nowait, token)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, sentinel)

        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(_producer)
            while True:
                item = await queue.get()
                if item is sentinel:
                    break
                yield item
