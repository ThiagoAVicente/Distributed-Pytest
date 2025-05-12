FROM python:3.9-slim

WORKDIR /app

# copy files
ADD src/ /app
ADD requirements.txt /app/requirements.txt

# install dependencies
RUN pip install --no-cache-dir --upgrade -r requirements.txt

# run node
CMD ["python","initNode.py"] 