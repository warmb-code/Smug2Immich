FROM docker.io/library/python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY Smug2Immich.py .

# Config and state files persist via mounted volume
VOLUME /app/data

ENV PYTHONUNBUFFERED=1
ENV SMUG2IMMICH_DATA_DIR=/app/data

ENTRYPOINT ["python", "Smug2Immich.py"]
