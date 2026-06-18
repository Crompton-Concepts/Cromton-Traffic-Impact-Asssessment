FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY report_service.py ./report_service.py

# Run as a non-root user to limit blast radius of any RCE in the service/deps.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "report_service:app", "--host", "0.0.0.0", "--port", "8080"]
