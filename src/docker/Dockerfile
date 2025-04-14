FROM python:3.13-slim

WORKDIR /app

# copy files
COPY docker/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY app/initNode.py .
COPY app/node.py .
COPY app/protocol.py .

# run initNode.py
CMD ["python", "initNode.py"]
