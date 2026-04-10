import asyncio
import random

# Simula una llamada lenta, por ejemplo una API externa
async def obtener_datos_cliente(id_cliente):
    print(f"[{id_cliente}] Consulta iniciada...")

    # Simula una espera variable
    tiempo_espera = random.uniform(0.5, 2.0)
    await asyncio.sleep(tiempo_espera)  

    print(f"[{id_cliente}] Datos recibidos tras {tiempo_espera:.2f}s")
    return {"cliente": id_cliente, "tiempo": tiempo_espera}


async def main():
    # Creamos tareas asíncronas
    tareas = [
        asyncio.create_task(obtener_datos_cliente("A")),
        asyncio.create_task(obtener_datos_cliente("B")),
        asyncio.create_task(obtener_datos_cliente("C"))
    ]

    print("Lanzadas todas las consultas...\n")

    # Esperamos a que terminen todas (¡a la vez!)
    resultados = await asyncio.gather(*tareas)

    print("\nResultados finales:")
    for r in resultados:
        print(r)

# Ejecutamos
asyncio.run(main())