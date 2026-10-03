# Candidate execution image. Pinned by digest so every run uses the same runtime.
FROM python@sha256:bb2988715db2cf7ace7b53f38f3cffbef7c7046a656bee66245eb0ed386e2e81

COPY worker.py /opt/worker/worker.py

# Isolated mode ignores environment variables and user site-packages.
ENTRYPOINT ["python", "-I", "/opt/worker/worker.py"]
