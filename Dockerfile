FROM python:3.11
WORKDIR /app
COPY artifacts/histovest/backend/requirements.txt .
RUN pip install -r requirements.txt
COPY artifacts/histovest/backend .
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
