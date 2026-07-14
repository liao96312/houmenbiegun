FROM python:3.12-slim

WORKDIR /app
COPY . .
EXPOSE 8000
ENV PORT=8000
ENV HOST=0.0.0.0
CMD ["python", "-m", "app.server"]
