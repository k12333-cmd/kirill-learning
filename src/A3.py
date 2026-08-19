import os
folder = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(folder, 'расходы.csv')
stats = {}
with open(path, 'r', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if line == '':
            continue
        cat, num = line.split(',')
        try:
            num = int(num)
        except ValueError:
            print("ошибочка", line)
            continue
        if cat not in stats:
            stats[cat] = {'sum': 0, 'count': 0}
        stats[cat]['sum'] += num
        stats[cat]['count'] += 1
total = 0
for cat in stats:
    s = stats[cat]['sum']
    c = stats[cat]['count']
    avg = round(s / c, 1)
    print(cat, ": всего", s, ", среднее", avg)
    total += s
print("сумм по всем категориям:", total)
