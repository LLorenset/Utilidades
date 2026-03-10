import sys
from PyQt6.QtWidgets import (QApplication, QDialog, QFormLayout, 
                             QLineEdit, QDoubleSpinBox, QSpinBox, 
                             QPushButton, QVBoxLayout, QMessageBox)

class VentanaProducto(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Entrada de Producto - ERP")
        self.setMinimumWidth(350)
        
        # 1. Diseño de Formulario
        self.layout_formulario = QFormLayout()
        
        # 2. Campos de entrada
        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Ej: PROD-001")
        
        self.nombre = QLineEdit()
        
        self.cantidad = QSpinBox()
        self.cantidad.setRange(0, 10000)
        
        self.precio = QDoubleSpinBox()
        self.precio.setRange(0, 999999.99)
        self.precio.setPrefix("$ ")

        # Añadir filas (Etiqueta, Control)
        self.layout_formulario.addRow("Código:", self.codigo)
        self.layout_formulario.addRow("Descripción:", self.nombre)
        self.layout_formulario.addRow("Stock Inicial:", self.cantidad)
        self.layout_formulario.addRow("Precio Costo:", self.precio)

        # 3. Botón de Guardar
        self.btn_guardar = QPushButton("Guardar en Servidor")
        self.btn_guardar.clicked.connect(self.procesar_datos)

        # Diseño principal
        layout_principal = QVBoxLayout()
        layout_principal.addLayout(self.layout_formulario)
        layout_principal.addWidget(self.btn_guardar)
        self.setLayout(layout_principal)

    def procesar_datos(self):
        # Aquí capturas los datos para enviarlos al Servidor/DB
        data = {
            "id": self.codigo.text(),
            "nom": self.nombre.text(),
            "qty": self.cantidad.value(),
            "prc": self.precio.value()
        }
        
        if not data["id"] or not data["nom"]:
            QMessageBox.warning(self, "Error", "Faltan campos obligatorios")
        else:
            print(f"Enviando al servidor: {data}")
            QMessageBox.information(self, "Éxito", "Datos listos para enviar")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = VentanaProducto()
    ventana.show()
    sys.exit(app.exec())
