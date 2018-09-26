from .tasks import longtime_add
import time
if __name__ == '__main__':
    result = longtime_add.delay()
    print 'Task result:', result.result
