# The ViksitGaanw sync service, for any container host.
#
#   docker build -t viksitgaanw-sync apps/sync
#   docker run -p 8900:8900 \
#     -e VG_SYNC_DATABASE_URL=postgresql://user:password@host:5432/viksitgaanw \
#     viksitgaanw-sync
#
# TLS is the host's job: put it behind the host's HTTPS load balancer or a
# reverse proxy, which is also why X-Forwarded-For is trusted here. Keys
# (Mux, Razorpay) come in as environment variables, never baked into the image.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py storage.py admin.py ./

RUN useradd --create-home --uid 10001 sync && mkdir -p /app/data && chown sync /app/data
USER sync

ENV VG_SYNC_TRUST_PROXY=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8900
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8900", "--workers", "2", "--proxy-headers", "--forwarded-allow-ips", "*"]
