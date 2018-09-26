from celery import Celery

app = Celery('tasks', broker='amqp://admin:password@rabbit:5672',backend='rpc://',include=['tasks.tasks'])
