FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 taskify \
    && useradd --uid 10001 --gid taskify --no-create-home taskify \
    && install -d -o taskify -g taskify /data

COPY bot/ bot/
COPY database/ database/
COPY web/ web/
COPY run_bot.py run_web.py ./

USER taskify
EXPOSE 5000

CMD ["python", "run_web.py"]
