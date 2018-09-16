
from __future__ import absolute_import
from tasks.celery import app
import time, requests

@app.task(bind=True,default_retry_delay=10) # set a retry delay, 10 equal to 10s
def longtime_add(self):
    with open('x.txt' , 'w+') as fh:
        fh.write('hello')
