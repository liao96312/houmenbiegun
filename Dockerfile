FROM python:3.12-slim

WORKDIR /app
COPY . .
EXPOSE 8000
# 容器内必须监听 0.0.0.0，端口映射才能从宿主机访问到
ENV HOST=0.0.0.0
ENV PORT=8000
CMD ["python", "-m", "app.server"]
