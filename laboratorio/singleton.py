class Ejemplo:
    atributo_clase = "Soy de la clase"

    def __init__(self, valor):
        # 'self' es el objeto específico que acabas de crear
        self.atributo_instancia = valor

    @classmethod
    def metodo_de_clase(cls):
        # 'cls' se refiere a la "fábrica" (la clase Ejemplo)
        return f"Accediendo a: {cls.atributo_clase}"

# Uso
objeto_a = Ejemplo("Instancia A")
objeto_b = Ejemplo("Instancia B")

print(objeto_a.atributo_instancia) # Cada uno tiene su propio 'self'
print(objeto_a.metodo_de_clase()) # Cada uno tiene su propio 'self'
print(Ejemplo.metodo_de_clase())   # 'cls' es común para todos