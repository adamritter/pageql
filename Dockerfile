FROM python:3.11-slim

WORKDIR /app

# Copy required files and install PageQL
COPY pyproject.toml README.md ./
COPY src ./src
COPY website ./website
RUN pip install .

EXPOSE 8000

# Mount database and templates at runtime
VOLUME ["/data", "/app/website"]

ENTRYPOINT ["pageql"]
CMD ["/app/website", "/data/data.db", "--create", "--host", "0.0.0.0"]
