FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN mkdir -p /data
ENV DATABASE=/data/bazaar.db
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:create_app()"]
