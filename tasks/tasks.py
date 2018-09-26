from __future__ import absolute_import, unicode_literals
from .celery import app

@app.task
def longtime_add():
    with open('x.txt' , 'w+') as fh:
        fh.write('hello')
