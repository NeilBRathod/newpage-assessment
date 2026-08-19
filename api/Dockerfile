FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies against the package metadata alone, so editing source
# does not invalidate the slow dependency layer. The editable install means the
# later COPY of src/ is picked up without reinstalling.
COPY pyproject.toml ./
COPY src/meetingiq/__init__.py ./src/meetingiq/__init__.py
RUN pip install -e ".[dev]"

COPY src/ ./src/
COPY tests/ ./tests/

EXPOSE 8000
CMD ["uvicorn", "meetingiq.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
