FROM python:3.15-slim
RUN pip install --no-cache-dir fastmcp==4.2.0 scipy==1.18.1 numpy==2.5.4
WORKDIR /app
COPY sim.py optimum.py server.py ./
CMD ["python", "server.py"]
