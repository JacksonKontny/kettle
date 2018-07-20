import numpy

with open('post_sentiment.csv', 'r') as fh:
    max_s = []
    min_s = []
    avg_s = []

    for line in fh.readlines():
        line = line.split(',')
        max_s.append(float(line[0]))
        min_s.append(float(line[1]))
        try:
            avg_s.append(float(line[2]))
        except Exception as e:
            pass

def get_perc(perc):
    print('max perc: ', numpy.percentile(max_s, 100 - perc))
    print('min perc: ', numpy.percentile(min_s, perc))
    print('max avg perc: ', numpy.percentile(avg_s, 100 - perc))
    print('min avg perc: ', numpy.percentile(avg_s, perc))
    print('\n')

print(avg_s)
get_perc(.2)
get_perc(1)
get_perc(5)
