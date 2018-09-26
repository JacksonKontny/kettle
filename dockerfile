FROM python:3.6
ADD requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
WORKDIR /app/
ADD ./tasks/ /app/
