## 2024-05-10 - Event Loop Blocking in Async FastAPI Routes
**Learning:** Calling synchronous network operations (like `urllib.request.urlopen`) directly inside an `async def` route in FastAPI blocks the event loop, preventing concurrent request handling.
**Action:** Always wrap synchronous blocking I/O calls in `asyncio.to_thread()` when operating within an asynchronous route, or convert the route to a standard `def` (which FastAPI automatically runs in a thread pool).
