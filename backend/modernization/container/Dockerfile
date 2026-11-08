FROM python:3.11-slim

# Only the standard-library monitor runs here. No repository or secrets are copied.
WORKDIR /work
USER 65534:65534
ENTRYPOINT ["python", "-I", "-S", "/work/monitor.py"]
