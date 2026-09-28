import os
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

def crear_pdf_perfecto():
    pdf_filename = "tabla_bincodec_actualizada.pdf"
    
    # Dimensiones exactas A4 Vertical con márgenes súper reducidos (12 pt = 0.42 cm)
    doc = SimpleDocTemplate(
        pdf_filename,
        pagesize=(595.27, 841.89),
        leftMargin=12, rightMargin=12, topMargin=12, bottomMargin=12
    )
    
    story = []
    raw_data = [["" for _ in range(16)] for _ in range(65)]
    
    # Inicializar las cabeceras de los 4 bloques
    for b in range(4):
        c_base = b * 4
        raw_data[0][c_base] = "DEC"
        raw_data[0][c_base+1] = "HEX"
        raw_data[0][c_base+2] = "C"
        raw_data[0][c_base+3] = "PROTOCOLO"
        
    # Inicialización de vectores base (0-255)
    protocolo = [""] * 256
    ascii_c = [""] * 256
    
    mnemonicos = ["NUL","SOH","STX","ETX","EOT","ENQ","ACK","BEL","BS","HT","LF","VT","FF","CR","SO","SI",
                  "DLE","DC1","DC2","DC3","DC4","NAK","SYN","ETB","CAN","EM","SUB","ESC","FS","GS","RS","US"]
    for i in range(32): ascii_c[i] = mnemonicos[i]
    ascii_c[127] = "DEL"
    for i in range(32, 255): ascii_c[i] = chr(i)
        
    # Mapeos específicos del bincodec corregido
    protocolo[0] = protocolo[1] = "RESERVADO KV"
    protocolo[9] = "SKIP INTERMEDIO"
    protocolo[16] = "RECORD_EMPTY"
    protocolo[17], protocolo[18], protocolo[19], protocolo[20] = "RECORD_START 1", "RECORD_START 2", "RECORD_START 3", "RECORD_START 4"

    protocolo[21], protocolo[22], protocolo[23], protocolo[24], protocolo[25] = "TABLE_START 1", "TABLE_START 2", "TABLE_START 3", "TABLE_START 4", "TABLE_START 5"
    #protocolo[26], protocolo[27], protocolo[28] = "SET_MOD", "FROZENSET_MOD", "TUPLE_MOD"
    
    protocolo[32] = "LIST_EMPTY"
    protocolo[33], protocolo[34], protocolo[35], protocolo[36], protocolo[37] = "LIST_START 1", "LIST_START 2", "LIST_START 3", "LIST_START 4", "LIST_START 5"
    protocolo[40], protocolo[38], protocolo[39] = "TUPLE_MOD", "SET_MOD", "FROZENSET_MOD"
    
    for i in range(16): protocolo[48 + i] = f"STR OPT LEN {i+1}"
    protocolo[64] = "STR VACIO (**)"
    for i in range(4): protocolo[65 + i] = f"STR LEN {i+1}"
    protocolo[69], protocolo[70] = "STR = 'S'", "STR = 'N'"
    
    protocolo[80] = "BYTES VACIO"
    for i in range(5): protocolo[81 + i] = f"BYTES LEN {i+1}"
    for i in range(4): protocolo[86 + i] = f"BYTES EXT LEN {i+1}"
        
    protocolo[96] = "INT-0"
    protocolo[97], protocolo[98], protocolo[99], protocolo[100] = "INT 8", "INT 16", "INT 32 (3B)", "INT 32 (4B)"
    for i in range(4): protocolo[101 + i] = f"INT 64 ({5+i}B)"
    protocolo[105], protocolo[106] = "INT = 1", "INT = -1"
    
    protocolo[112] = "UINT-0"
    protocolo[113], protocolo[114], protocolo[115], protocolo[116] = "UINT 8", "UINT 16", "UINT 32 (3B)", "UINT 32 (4B)"
    for i in range(4): protocolo[117 + i] = f"UINT 64 ({5+i}B)"
    protocolo[121] = "UINT = 1"
    
    protocolo[128], protocolo[124], protocolo[136], protocolo[137] = "FLOAT-0", "FLOAT 32", "FLOAT 64", "FLOAT-1"
    protocolo[144], protocolo[145], protocolo[146], protocolo[147] = "DATE NONE", "DATE 3B", "DATETIME NONE", "DATETIME 5B"
    protocolo[148], protocolo[149] = "TIME NONE", "TIME 3B"
    
    protocolo[160] = "MAP_EMPTY"
    for i in range(4): protocolo[161 + i] = f"MAP_START {i+1}"
    protocolo[165], protocolo[168], protocolo[169] = "NULL_VALUE", "STRUCT_MAP_MOD", "STRUCT_LIST_MOD"
    protocolo[176], protocolo[177], protocolo[178] = "BOOL NONE", "BOOL FALSE", "BOOL TRUE"
    
    ascii_c[128], ascii_c[131], ascii_c[137], ascii_c[140], ascii_c[153] = "EUR", "f", "o/oo", "OE", "(R)"
    ascii_c[160], ascii_c[163], ascii_c[169], ascii_c[174], ascii_c[176], ascii_c[177] = "SP", "L", "(C)", "(R)", "deg", "+/-"
    ascii_c[188], ascii_c[189], ascii_c[190] = "1/4", "1/2", "3/4"
    
    # Construcción de la matriz por bloques
    for v in range(256):
        b = v // 64
        f = (v % 64) + 1
        c = b * 4
        raw_data[f][c], raw_data[f][c+1], raw_data[f][c+2], raw_data[f][c+3] = str(v), f"0x{v:02X}", ascii_c[v], protocolo[v]

    # Distribución fija optimizada de anchos: Protocolo ensanchado a 88.5 puntos
    col_widths = [16, 26, 16, 88.5] * 4
    t = Table(raw_data, colWidths=col_widths, repeatRows=1)
    
    # Diseño de estilos (Azul Marino y Azul de corte técnico)
    t_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1A365D')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 6.5),
        ('ALIGN', (0,0), (-1,0), 'CENTER'),
        ('VALIGN', (0,0), (-1,0), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 2.5),
        ('TOPPADDING', (0,0), (-1,0), 2.5),
    ]
    
    # Inyección de las propiedades por fila: Padding 0.1pt y Fuentes de 5.8pt
    for f in range(1, 65):
        bg = colors.HexColor('#F7FAFC') if f % 2 == 0 else colors.white
        t_style.append(('BACKGROUND', (0, f), (-1, f), bg))
        for b in range(4):
            c = b * 4
            t_style.extend([
                ('ALIGN', (c, f), (c+2, f), 'CENTER'), ('ALIGN', (c+3, f), (c+3, f), 'LEFT'),
                ('FONTNAME', (c, f), (c+1, f), 'Helvetica'), ('FONTNAME', (c+2, f), (c+2, f), 'Helvetica'),
                ('FONTNAME', (c+3, f), (c+3, f), 'Helvetica-Bold'), ('FONTSIZE', (c, f), (c+3, f), 5.8),
                ('TEXTCOLOR', (c, f), (c+2, f), colors.HexColor('#4A5568')), ('TEXTCOLOR', (c+3, f), (c+3, f), colors.HexColor("#1a365d"))##2D3748
            ])
        t_style.extend([('TOPPADDING', (0, f), (-1, f), 0.1), ('BOTTOMPADDING', (0, f), (-1, f), 0.1), ('VALIGN', (0, f), (-1, f), 'MIDDLE')])

    # Líneas divisorias en azul medio de los 4 bloques principales
    t_style.extend([
        ('LINEBEFORE', (4, 0), (4, -1), 1.5, colors.HexColor('#2B6CB0')),
        ('LINEBEFORE', (8, 0), (8, -1), 1.5, colors.HexColor('#2B6CB0')),
        ('LINEBEFORE', (12, 0), (12, -1), 1.5, colors.HexColor('#2B6CB0'))
    ])
    
    t.setStyle(TableStyle(t_style))
    story.append(t)
    doc.build(story)
    print("¡Hecho! 'tabla_bincodec_actualizada.pdf' ha sido creado en tu carpeta actual con una única página.")

if __name__ == "__main__":
    crear_pdf_perfecto()
