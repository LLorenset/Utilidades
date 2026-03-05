class Persona:
    especie = "humano"   # atributo de clase
    def cambia(self, nueva_especie):
        self.especie = nueva_especie  # crea un atributo de instancia

    def saludar(self):
        return "Hola "+self.especie


    
p1 = Persona()
p2 = Persona()
p3 = Persona()
p4 = Persona()

x = 5

print(p1.especie, p2.especie, p3.especie)  # humano humano humano


p1.especie = "mutante"
p2.cambia("extraterrestre")

print(p1.especie, p2.especie, p3.especie)  #  mutante extraterrestre humano



print(p1.__dict__)         # Solo atributos de instancia
print(p2.__dict__)         # Solo atributos de instancia
print(Persona.__dict__)   # Atributos de clase
print(p3.__dict__)         # Solo atributos de instancia
#print(x.__dict__)          # No tiene __dict__ porque es un int (tipo primitivo)

print(id(x), id(p1.especie), id(p2.especie), id(p3.especie), id(p4.especie))  # Mismo id para el atributo de clase "humano" en p3, diferente para p1 y p2

print(id(p1), id(p2), id(p3), id(p4))  

print(Persona.saludar(p1))  # Llamada a método usando la clase, pasando la instancia como argumento
print(p1.saludar())         # Llamada a método usando la instancia, se pasa implícitamente la instancia como argumento

print(id(p1), id(Persona))  
print(id(p1.saludar), id(Persona.saludar))  

Persona.saludar = p1.saludar  # Asignamos el método de la clase a la instancia, creando un nuevo atributo de instancia

print(id(p1.saludar), id(Persona.saludar))  

print(p1.saludar())         # Llamada a método usando la instancia, se pasa implícitamente la instancia como argumento
print(Persona.saludar())  # Llamada a método usando la clase, pasando la instancia como argumento
print(p2.saludar())         # Llamada a método usando la instancia, se pasa implícitamente la instancia como argumento

print(p1.__dict__)         # Solo atributos de instancia
print(p2.__dict__)         # Solo atributos de instancia
print(Persona.__dict__)   # Atributos de clase
print(p3.__dict__)         # Solo atributos de instancia

import types

def nuevo_saludo(self):
    return f"Hola desde nuevo_saludo, {self.especie}"

p1.saludar = types.MethodType(nuevo_saludo, p1)

print(p1.saludar())
print(p2.saludar())

Persona.saludar = nuevo_saludo

print(p1.saludar())
print(p2.saludar())
