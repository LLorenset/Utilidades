class P:
    def __init__(self):
        pass

p = P()

print(p.__dict__)  # {}

p.edad = 30

print(p.__dict__)  # {'edad': 30}
