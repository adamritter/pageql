FROM python:3.11-slim

WORKDIR /app

# Copy required files and install PageQL
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

EXPOSE 8000

# Mount database and templates at runtime
VOLUME ["/data", "/templates"]

ENTRYPOINT ["pageql"]
CMD ["/data/data.db", "/templates", "--create"]
