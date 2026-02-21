FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "protobuf==6.32.1"

# Copy source
COPY msgs/ ./msgs/
COPY examples/TCP_library.py ./examples/TCP_library.py
COPY examples/heartbeat_server.py ./examples/heartbeat_server.py
COPY examples/__init__.py ./examples/__init__.py
COPY msgs/__init__.py ./msgs/__init__.py

# Make packages importable without editable install
ENV PYTHONPATH=/app

EXPOSE 50000/tcp
EXPOSE 8080/tcp

RUN mkdir /logs
VOLUME ["/logs"]

CMD ["python", "-m", "examples.heartbeat_server", "--log-dir=/logs"]
