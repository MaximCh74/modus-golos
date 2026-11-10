FROM python:3.10-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MF_DATA_DIR=/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mf ./mf
COPY web ./web
COPY tools ./tools
EXPOSE 8080
CMD ["python3", "-m", "uvicorn", "mf.main:app", "--host", "0.0.0.0", "--port", "8080"]
