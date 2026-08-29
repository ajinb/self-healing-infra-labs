FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "pydantic>=2.9" \
    pydantic-settings anthropic structlog httpx
ENV PYTHONPATH=/app/src
EXPOSE 8081
# Deploys alongside Alertmanager; Alertmanager posts to /enrich.
CMD ["uvicorn", "alert_explainer.service:app", "--host", "0.0.0.0", "--port", "8081"]
