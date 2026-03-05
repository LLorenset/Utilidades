class Persona:
    def saludar(self):
        return f"Hola soy {self.nombre}"

p = Persona()
p.nombre = "Lorenzo"

print(p.saludar())
