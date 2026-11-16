FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DOCMIND_EMBEDDING_PROVIDER=hashing \
    DOCMIND_GENERATOR=extractive

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY docmind ./docmind
COPY corpus ./corpus
COPY static ./static

# Build the index at image build time so the container serves immediately.
RUN python -m docmind.ingest

RUN useradd --create-home --shell /bin/bash docmind && chown -R docmind:docmind /app
USER docmind

EXPOSE 8200
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8200/health').status==200 else 1)"

CMD ["uvicorn", "docmind.service:app", "--host", "0.0.0.0", "--port", "8200"]
