class Carrito(object):
    def __new__(cls, *args, **kwargs):
        print('__new__')
        
        return super().__new__(cls)

    def __init__(self):
        print('__init__')
        self._items = []

    def __str__(self):
        print('__str__')
        return "Carrito({})".format(self._items)
    
    def __repr__(self):
        print('__repr__')
        return "Carrito({})".format(self._items)

    def __del__(self):
        print('__del__')

    def __iter__(self):
        print('__iter__')
        return iter(self._items)
    
    def __next__(self):
        print('__next__')
        return next(self._items)

    def __contains__(self, item):
        print('__contains__')
        return item in self._items
    
    def __eq__(self, other):
        print('__eq__')
        return self._items == other._items

    def __ne__(self, other):
        print('__ne__')
        return self._items != other._items

    def __lt__(self, other):
        print('__lt__')
        return self._items < other._items

    def __le__(self, other):
        print('__le__')
        return self._items <= other._items
    
    def __gt__(self, other):
        print('__gt__')
        return self._items > other._items
    def __ge__(self, other):
        print('__ge__')
        return self._items >= other._items
    
    def __bool__(self):
        print('__bool__')
        return bool(self._items)

    def __hash__(self):
        print('__hash__')
        return hash(self._items)
    


    def __len__(self):
        print('__len__')
        return len(self._items)

    def __getitem__(self, index):
        print('__getitem__')
        return self._items[index]

    def __add__(self, item):
        nuevo = Carrito()
        nuevo._items = self._items + [item]
        return nuevo

    def add(self, item):
        self._items.append(item)



c = Carrito()
c.add("ratón")
c.add("teclado")
for item in c._items:
    print(item)

print(len(c))          # 2
print(c[1])            # teclado
print(c + "monitor")   # nuevo carrito
print(c)               # Carrito(['ratón', 'teclado'])
