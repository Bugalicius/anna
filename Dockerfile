FROM python:3.12-slim
WORKDIR /app

# Dependências do sistema para Playwright/Chromium
RUN apt-get update && apt-get install -y \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpango-1.0-0 libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Instala binários do Chromium para Playwright
RUN playwright install chromium

COPY . .
RUN python -c "from pathlib import Path; head=Path('.git/HEAD'); version='unknown'; ref=''; \
ref=head.read_text().strip() if head.exists() else ''; \
target=Path('.git') / ref.split(' ', 1)[1] if ref.startswith('ref: ') else None; \
version=(target.read_text().strip()[:7] if target and target.exists() else (ref[:7] if ref and not ref.startswith('ref: ') else version)); \
Path('.app_version').write_text(version)"
CMD ["sh", "-c", "export APP_VERSION=${APP_VERSION:-$(cat /app/.app_version 2>/dev/null || echo unknown)}; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
