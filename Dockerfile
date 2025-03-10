FROM python:3.11
WORKDIR /app
COPY . /app
RUN pip install fastapi 'uvicorn[standard]'
RUN pip install -r requirements.txt
CMD ["uvicorn", "asr_server:app", "--host", "0.0.0.0", "--port", "5000", "--log-level", "warning", "--workers", "4"]
