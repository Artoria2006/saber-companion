FROM python:3.11.15-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base'); tiktoken.get_encoding('o200k_base')"
COPY bot.py chat.py settings.py storage.py reading.py ./
CMD ["python", "bot.py"]
