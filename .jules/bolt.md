
## 2024-05-08 - Caching static base64 assets in Python
**Learning:** `_load_logo_data_url` in `report_service.py` was reading and base64-encoding an image on disk for every report generation.
**Action:** Use `@functools.lru_cache()` for static assets that don't change at runtime to eliminate repeated disk I/O and CPU overhead.
