FROM python:3.6
ADD requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt
RUN python -m nltk.downloader vader_lexicon
WORKDIR /app/
ADD ./tasks/ /app/
