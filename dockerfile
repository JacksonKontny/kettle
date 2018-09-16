FROM python:3.6
ADD requirements.txt /app/requirements.txt
ADD ./tasks/ /app/
WORKDIR /app/
RUN pip install -r requirements.txt
ENTRYPOINT celery -A tasks worker --concurrency=1 --loglevel=info
