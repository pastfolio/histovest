FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD uvicorn artifacts/histovest/backend/main:app --host 0.0.0.0 --port $PORT
