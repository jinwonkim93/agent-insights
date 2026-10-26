FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AI_HOST=0.0.0.0 AI_AUTO_CREATE_SCHEMA=false
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir '.[postgres]' && useradd --uid 10001 --create-home insights
USER insights
EXPOSE 8766
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8766/ready', timeout=3)"
ENTRYPOINT ["agent-insights"]
CMD ["serve"]
