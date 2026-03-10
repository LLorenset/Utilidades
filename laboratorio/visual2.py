import wx

class VentanaERP(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title='Entrada de Datos - wxPython ERP', size=(400, 300))
        panel = wx.Panel(self)
        
        # 1. Contenedor principal con márgenes
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        # 2. Grid para alinear etiquetas y campos (Filas, Columnas, EspacioV, EspacioH)
        fgs = wx.FlexGridSizer(4, 2, 10, 10)

        # Campos de entrada
        self.txt_codigo = wx.TextCtrl(panel)
        self.txt_nombre = wx.TextCtrl(panel)
        self.spn_cantidad = wx.SpinCtrl(panel, value='0', min=0, max=10000)
        self.txt_precio = wx.TextCtrl(panel) # wx no tiene DoubleSpin nativo tan directo

        # Añadir al Grid
        fgs.AddMany([
            (wx.StaticText(panel, label="Código: ")), (self.txt_codigo, 1, wx.EXPAND),
            (wx.StaticText(panel, label="Producto: ")), (self.txt_nombre, 1, wx.EXPAND),
            (wx.StaticText(panel, label="Stock: ")), (self.spn_cantidad, 1, wx.EXPAND),
            (wx.StaticText(panel, label="Precio: ")), (self.txt_precio, 1, wx.EXPAND)
        ])
        
        fgs.AddGrowableCol(1, 1) # Hacer que la columna de los campos crezca

        # 3. Botón de acción
        btn_guardar = wx.Button(panel, label="Registrar en ERP")
        btn_guardar.Bind(wx.EVT_BUTTON, self.on_save)

        # Ensamblar todo
        main_sizer.Add(fgs, 1, wx.ALL | wx.EXPAND, 15)
        main_sizer.Add(btn_guardar, 0, wx.ALIGN_CENTER | wx.BOTTOM, 15)
        
        panel.SetSizer(main_sizer)
        self.Show()

    def on_save(self, event):
        # Lógica de captura
        nombre = self.txt_nombre.GetValue()
        if not nombre:
            wx.MessageBox("El nombre es obligatorio", "Error", wx.OK | wx.ICON_ERROR)
        else:
            print(f"Guardando: {nombre}...")
            wx.MessageBox("Datos enviados al servidor", "Éxito", wx.OK | wx.ICON_INFORMATION)

if __name__ == '__main__':
    app = wx.App()
    VentanaERP()
    app.MainLoop()
