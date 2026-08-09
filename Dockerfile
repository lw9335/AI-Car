FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN groupadd --system roadmind && useradd --system --gid roadmind --create-home roadmind
COPY --chown=roadmind:roadmind pyproject.toml README.md ./
COPY --chown=roadmind:roadmind src ./src
RUN pip install --no-cache-dir .

USER roadmind

EXPOSE 8000 8001
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')"
CMD ["uvicorn", "roadmind.main:app", "--host", "0.0.0.0", "--port", "8000"]
