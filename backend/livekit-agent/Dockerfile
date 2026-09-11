FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py groq_llm.py key_loader.py ./

# Memory trims for small containers (Render free = 512MB; a live call
# peaks ~350-400MB across worker procs). Single-threaded numeric libs
# avoid per-thread pool duplication; unbuffered logs stay attached.
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV PYTHONUNBUFFERED=1

# Render/HF health check: $PORT is injected by Render; default 7860 elsewhere.
# The worker runs in the foreground so container logs stay attached; the
# health server is a background companion only (worker needs no inbound port).
EXPOSE 7860

CMD ["sh", "-c", "python -m http.server ${PORT:-7860} & exec python agent.py start"]
