FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MF_DATA_DIR=/data MF_DEMO_SNAPSHOT=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mf ./mf
COPY web ./web
COPY tools ./tools
# демо-снапшот: при первом старте пустая база заполняется им сама (даты сдвигаются на «сегодня»)
COPY demo/fixtures/mf-demo.db ./demo/fixtures/mf-demo.db
EXPOSE 8080
CMD ["python3", "-m", "uvicorn", "mf.main:app", "--host", "0.0.0.0", "--port", "8080"]
