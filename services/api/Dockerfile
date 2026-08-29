FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data
COPY load_data.py .

EXPOSE 8000
CMD ["sh", "-c", "python load_data.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

