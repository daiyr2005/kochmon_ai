FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY req.txt ./req.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r req.txt

COPY . ./

EXPOSE 8000
CMD ["uvicorn", "mysite.standalone_routes.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
