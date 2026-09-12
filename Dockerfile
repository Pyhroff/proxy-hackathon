# Base image already has Chromium + all its OS-level dependencies
# preinstalled and version-matched to a specific Playwright release --
# far simpler than installing Playwright's browser deps by hand on a
# generic Python image. Pin the tag to the Playwright version in
# requirements.txt (currently 1.58.0) if you bump that version.
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
