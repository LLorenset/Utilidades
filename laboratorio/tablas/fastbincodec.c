/*
===============================================================================
Responsabilidad

Extensión CPython mínima para decodificar registros bincodec completos desde
payloads Pebble como los usados en los benchmarks de HI. El objetivo no es
replicar todo el ecosistema del codec, sino acelerar el camino que hoy hace
Python puro recorriendo el registro campo a campo.

Flujo

1. Recibe un buffer Python (`bytes`, `bytearray`, `memoryview`, ...).
2. Recorre el payload completo, respetando marcadores `TAG_SKIP` de nivel raíz.
3. Decodifica cada campo a objetos Python nativos: `str`, `int`, `float`,
   `bytes`, `list`, `dict`, `tuple`, `set`, `frozenset`, `None`.
4. Devuelve la lista de valores presentes en el registro.

Diseño

 - Está orientado a decode completo del registro, no a `decode_at` con esquema.
 - Para la comparación final también expone dos caminos de proyección cruda que
     no materializan objetos Python: localizan spans del payload y simulan un
     `SELECT` reserializando solo el subconjunto pedido en un buffer interno.
- Implementa los tags necesarios para el benchmark y para estructuras anidadas
  frecuentes en HI: strings, enteros, fechas, listas, mapas y modificadores de
  colección/struct.
- `TAG_SKIP` se ignora en el nivel raíz igual que hace el benchmark Python
  actual: no inserta placeholders para campos omitidos.
- Si aparece un tag no soportado o un payload truncado, se devuelve `ValueError`.
===============================================================================
*/

#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include <stdint.h>
#include <string.h>

#define TAG_SKIP 0x09

#define TAG_RECORD_EMPTY 0x10
#define TAG_RECORD1 0x11
#define TAG_RECORD2 0x12
#define TAG_RECORD3 0x13
#define TAG_RECORD4 0x14

#define TAG_LIST_EMPTY 0x20
#define TAG_LIST1 0x21
#define TAG_LIST2 0x22
#define TAG_LIST3 0x23
#define TAG_LIST4 0x24

#define TAG_TUPLE_MOD 0x25
#define TAG_SET_MOD 0x26
#define TAG_FROZENSET_MOD 0x27

#define TAG_STRING_SHORT_BASE 0x30
#define TAG_STRING_SHORT_MAX 0x3F

#define TAG_STRING_EMPTY 0x40
#define TAG_STRING1 0x41
#define TAG_STRING2 0x42
#define TAG_STRING3 0x43
#define TAG_STRING4 0x44
#define TAG_STRING_S 0x45
#define TAG_STRING_N 0x46

#define TAG_BYTES_EMPTY 0x50
#define TAG_BYTES1 0x51
#define TAG_BYTES2 0x52
#define TAG_BYTES3 0x53
#define TAG_BYTES4 0x54

#define TAG_INT0 0x60
#define TAG_INT_LAST 0x68
#define TAG_INT_1 0x69
#define TAG_INT_NEG1 0x6A

#define TAG_UINT0 0x70
#define TAG_UINT_LAST 0x78
#define TAG_UINT_1 0x79

#define TAG_FLOAT0 0x80
#define TAG_FLOAT32 0x84
#define TAG_FLOAT64 0x88
#define TAG_FLOAT1 0x89

#define TAG_DATE_EMPTY 0x90
#define TAG_DATE 0x91
#define TAG_DATETIME_EMPTY 0x92
#define TAG_DATETIME 0x93
#define TAG_TIME_EMPTY 0x94
#define TAG_TIME 0x95

#define TAG_MAP_EMPTY 0xA0
#define TAG_MAP1 0xA1
#define TAG_MAP2 0xA2
#define TAG_MAP3 0xA3
#define TAG_MAP4 0xA4
#define TAG_NULL_VALUE 0xA5
#define TAG_STRUCT_MAP_MOD 0xA8
#define TAG_STRUCT_LIST_MOD 0xA9

#define TAG_BOOL_NONE 0xB0
#define TAG_BOOL_FALSE 0xB1
#define TAG_BOOL_TRUE 0xB2

#define TIME_NONE 9999999U

typedef struct {
    const unsigned char *data;
    Py_ssize_t len;
    Py_ssize_t off;
} Reader;

typedef struct {
    Py_ssize_t start;
    Py_ssize_t end;
    int found;
} Span;

static int reader_ensure(Reader *reader, Py_ssize_t need, const char *context) {
    if (need < 0 || reader->off < 0 || reader->off + need > reader->len) {
        PyErr_Format(PyExc_ValueError, "fastbincodec: payload truncado leyendo %s en offset %zd", context, reader->off);
        return 0;
    }
    return 1;
}

static uint64_t read_uint_be_raw(const unsigned char *data, int n) {
    uint64_t value = 0;
    int i;
    for (i = 0; i < n; i++) {
        value = (value << 8) | (uint64_t)data[i];
    }
    return value;
}

static int64_t read_int_be_raw(const unsigned char *data, int n) {
    uint64_t value = read_uint_be_raw(data, n);
    if (n > 0 && (data[0] & 0x80U) != 0) {
        value |= (~0ULL) << (n * 8);
    }
    return (int64_t)value;
}

static int is_immediate_tag(unsigned char tag) {
    switch (tag) {
        case TAG_RECORD_EMPTY:
        case TAG_BYTES_EMPTY:
        case TAG_STRING_EMPTY:
        case TAG_STRING_S:
        case TAG_STRING_N:
        case TAG_LIST_EMPTY:
        case TAG_MAP_EMPTY:
        case TAG_INT0:
        case TAG_INT_1:
        case TAG_INT_NEG1:
        case TAG_UINT0:
        case TAG_UINT_1:
        case TAG_FLOAT0:
        case TAG_FLOAT1:
        case TAG_DATE_EMPTY:
        case TAG_DATETIME_EMPTY:
        case TAG_TIME_EMPTY:
        case TAG_NULL_VALUE:
        case TAG_BOOL_NONE:
        case TAG_BOOL_FALSE:
        case TAG_BOOL_TRUE:
            return 1;
        default:
            return 0;
    }
}

static int is_modifier_tag(unsigned char tag) {
    return tag == TAG_TUPLE_MOD || tag == TAG_SET_MOD || tag == TAG_FROZENSET_MOD || tag == TAG_STRUCT_MAP_MOD || tag == TAG_STRUCT_LIST_MOD;
}

static int reader_skip_fixed(Reader *reader, Py_ssize_t size, const char *context) {
    if (!reader_ensure(reader, size, context)) {
        return 0;
    }
    reader->off += size;
    return 1;
}

static int reader_skip_blob(Reader *reader, int len_bytes, const char *context) {
    Py_ssize_t length;
    if (!reader_ensure(reader, len_bytes, context)) {
        return 0;
    }
    length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, len_bytes);
    reader->off += len_bytes;
    if (!reader_ensure(reader, length, context)) {
        return 0;
    }
    reader->off += length;
    return 1;
}

static int reader_skip_short_string(Reader *reader, unsigned char tag) {
    Py_ssize_t length = (Py_ssize_t)(tag - TAG_STRING_SHORT_BASE + 1);
    if (!reader_ensure(reader, length, "string corta")) {
        return 0;
    }
    reader->off += length;
    return 1;
}

static int reader_skip_value(Reader *reader) {
    unsigned char tag;

    if (!reader_ensure(reader, 1, "tag")) {
        return 0;
    }
    tag = reader->data[reader->off++];

    if (tag == TAG_SKIP) {
        return reader_skip_fixed(reader, 1, "TAG_SKIP");
    }
    if (is_immediate_tag(tag)) {
        return 1;
    }
    if (tag >= TAG_STRING_SHORT_BASE && tag <= TAG_STRING_SHORT_MAX) {
        return reader_skip_short_string(reader, tag);
    }
    if (tag >= TAG_STRING1 && tag <= TAG_STRING4) {
        return reader_skip_blob(reader, (int)(tag - TAG_STRING_EMPTY), "string");
    }
    if (tag >= TAG_BYTES1 && tag <= TAG_BYTES4) {
        return reader_skip_blob(reader, (int)(tag - TAG_BYTES_EMPTY), "bytes");
    }
    if (tag >= TAG_RECORD1 && tag <= TAG_RECORD4) {
        return reader_skip_blob(reader, (int)(tag - TAG_RECORD_EMPTY), "record");
    }
    if (tag >= TAG_LIST1 && tag <= TAG_LIST4) {
        return reader_skip_blob(reader, (int)(tag - TAG_LIST_EMPTY), "lista");
    }
    if (tag >= TAG_MAP1 && tag <= TAG_MAP4) {
        return reader_skip_blob(reader, (int)(tag - TAG_MAP_EMPTY), "mapa");
    }
    if (tag >= TAG_INT0 + 1 && tag <= TAG_INT_LAST) {
        return reader_skip_fixed(reader, (Py_ssize_t)(tag - TAG_INT0), "entero con signo");
    }
    if (tag >= TAG_UINT0 + 1 && tag <= TAG_UINT_LAST) {
        return reader_skip_fixed(reader, (Py_ssize_t)(tag - TAG_UINT0), "entero sin signo");
    }
    if (tag == TAG_FLOAT32) {
        return reader_skip_fixed(reader, 4, "float32");
    }
    if (tag == TAG_FLOAT64) {
        return reader_skip_fixed(reader, 8, "float64");
    }
    if (tag == TAG_DATE || tag == TAG_TIME) {
        return reader_skip_fixed(reader, 3, "fecha/hora");
    }
    if (tag == TAG_DATETIME) {
        return reader_skip_fixed(reader, 5, "datetime");
    }
    if (is_modifier_tag(tag)) {
        return reader_skip_value(reader);
    }

    PyErr_Format(PyExc_ValueError, "fastbincodec: tag no soportado en proyección 0x%02x en offset %zd", tag, reader->off - 1);
    return 0;
}

static int extract_second_list_item_span(const unsigned char *data, Py_ssize_t len, Py_ssize_t start, Span *span) {
    unsigned char tag;
    Py_ssize_t off = start + 1;
    Py_ssize_t length;
    Py_ssize_t content_start;
    Py_ssize_t content_end;
    Reader sub;
    int item_index = 0;

    if (start >= len) {
        PyErr_Format(PyExc_ValueError, "fastbincodec: offset de lista fuera de rango %zd", start);
        return 0;
    }

    tag = data[start];
    while (tag == TAG_TUPLE_MOD || tag == TAG_SET_MOD || tag == TAG_FROZENSET_MOD) {
        if (off >= len) {
            PyErr_Format(PyExc_ValueError, "fastbincodec: modificador de lista truncado en offset %zd", start);
            return 0;
        }
        tag = data[off++];
    }

    if (tag == TAG_LIST_EMPTY) {
        span->found = 0;
        return 1;
    }
    if (tag < TAG_LIST1 || tag > TAG_LIST4) {
        PyErr_Format(PyExc_ValueError, "fastbincodec: el campo 7 no contiene lista, tag 0x%02x", tag);
        return 0;
    }
    if (off + (tag - TAG_LIST_EMPTY) > len) {
        PyErr_SetString(PyExc_ValueError, "fastbincodec: longitud de lista truncada");
        return 0;
    }

    length = (Py_ssize_t)read_uint_be_raw(data + off, (int)(tag - TAG_LIST_EMPTY));
    content_start = off + (tag - TAG_LIST_EMPTY);
    content_end = content_start + length;
    if (content_end > len) {
        PyErr_SetString(PyExc_ValueError, "fastbincodec: contenido de lista truncado");
        return 0;
    }

    sub.data = data;
    sub.len = content_end;
    sub.off = content_start;
    while (sub.off < content_end) {
        Py_ssize_t item_start = sub.off;
        if (!reader_skip_value(&sub)) {
            return 0;
        }
        item_index++;
        if (item_index == 2) {
            span->start = item_start;
            span->end = sub.off;
            span->found = 1;
            return 1;
        }
    }

    span->found = 0;
    return 1;
}

static Py_ssize_t append_selected_span(char *buffer, Py_ssize_t out_off, const unsigned char *data, Span span) {
    if (!span.found) {
        buffer[out_off] = (char)TAG_NULL_VALUE;
        return out_off + 1;
    }
    memcpy(buffer + out_off, data + span.start, (size_t)(span.end - span.start));
    return out_off + (span.end - span.start);
}

static PyObject *project_record_length_common(PyObject *arg, int include_list_second) {
    Py_buffer view;
    Reader reader;
    Span field2 = {0, 0, 0};
    Span field4 = {0, 0, 0};
    Span field6 = {0, 0, 0};
    Span list2 = {0, 0, include_list_second ? 0 : 1};
    int field_index = 0;
    char *scratch = NULL;
    Py_ssize_t out_off = 0;
    PyObject *result = NULL;

    if (PyObject_GetBuffer(arg, &view, PyBUF_SIMPLE) < 0) {
        return NULL;
    }

    reader.data = (const unsigned char *)view.buf;
    reader.len = view.len;
    reader.off = 0;

    while (reader.off < reader.len) {
        Py_ssize_t start;
        if (!reader_ensure(&reader, 1, "tag raíz")) {
            PyBuffer_Release(&view);
            return NULL;
        }
        if (reader.data[reader.off] == TAG_SKIP) {
            if (!reader_ensure(&reader, 2, "TAG_SKIP")) {
                PyBuffer_Release(&view);
                return NULL;
            }
            reader.off += 2;
            continue;
        }

        start = reader.off;
        if (!reader_skip_value(&reader)) {
            PyBuffer_Release(&view);
            return NULL;
        }
        field_index++;

        if (field_index == 2) {
            field2.start = start;
            field2.end = reader.off;
            field2.found = 1;
        } else if (field_index == 4) {
            field4.start = start;
            field4.end = reader.off;
            field4.found = 1;
        } else if (field_index == 6) {
            field6.start = start;
            field6.end = reader.off;
            field6.found = 1;
        } else if (include_list_second && field_index == 7) {
            if (!extract_second_list_item_span(reader.data, reader.len, start, &list2)) {
                PyBuffer_Release(&view);
                return NULL;
            }
        }
    }

    scratch = (char *)PyMem_Malloc((size_t)view.len + 4U);
    if (scratch == NULL) {
        PyBuffer_Release(&view);
        return PyErr_NoMemory();
    }

    out_off = append_selected_span(scratch, out_off, reader.data, field2);
    out_off = append_selected_span(scratch, out_off, reader.data, field4);
    out_off = append_selected_span(scratch, out_off, reader.data, field6);
    if (include_list_second) {
        out_off = append_selected_span(scratch, out_off, reader.data, list2);
    }

    result = PyLong_FromSsize_t(out_off);
    PyMem_Free(scratch);
    PyBuffer_Release(&view);
    return result;
}

static PyObject *parse_value(Reader *reader);

static PyObject *parse_list_content(const unsigned char *data, Py_ssize_t length) {
    Reader sub = {data, length, 0};
    PyObject *list = PyList_New(0);
    if (list == NULL) {
        return NULL;
    }

    while (sub.off < sub.len) {
        PyObject *item = parse_value(&sub);
        if (item == NULL) {
            Py_DECREF(list);
            return NULL;
        }
        if (PyList_Append(list, item) < 0) {
            Py_DECREF(item);
            Py_DECREF(list);
            return NULL;
        }
        Py_DECREF(item);
    }

    return list;
}

static PyObject *parse_map_content(const unsigned char *data, Py_ssize_t length) {
    Reader sub = {data, length, 0};
    PyObject *dict = PyDict_New();
    if (dict == NULL) {
        return NULL;
    }

    while (sub.off < sub.len) {
        PyObject *key = parse_value(&sub);
        PyObject *key_str;
        PyObject *value;

        if (key == NULL) {
            Py_DECREF(dict);
            return NULL;
        }
        key_str = PyObject_Str(key);
        Py_DECREF(key);
        if (key_str == NULL) {
            Py_DECREF(dict);
            return NULL;
        }
        if (sub.off >= sub.len) {
            if (PyDict_SetItem(dict, key_str, Py_None) < 0) {
                Py_DECREF(key_str);
                Py_DECREF(dict);
                return NULL;
            }
            Py_DECREF(key_str);
            break;
        }

        value = parse_value(&sub);
        if (value == NULL) {
            Py_DECREF(key_str);
            Py_DECREF(dict);
            return NULL;
        }
        if (PyDict_SetItem(dict, key_str, value) < 0) {
            Py_DECREF(value);
            Py_DECREF(key_str);
            Py_DECREF(dict);
            return NULL;
        }
        Py_DECREF(value);
        Py_DECREF(key_str);
    }

    return dict;
}

static PyObject *wrap_sequence_modifier(unsigned char tag, PyObject *list_obj) {
    PyObject *result = NULL;

    if (tag == TAG_TUPLE_MOD) {
        result = PyList_AsTuple(list_obj);
    } else if (tag == TAG_SET_MOD) {
        result = PySet_New(list_obj);
    } else if (tag == TAG_FROZENSET_MOD) {
        result = PyFrozenSet_New(list_obj);
    } else {
        PyErr_Format(PyExc_ValueError, "fastbincodec: modificador de colección no soportado 0x%02x", tag);
    }

    return result;
}

static PyObject *parse_collection_modifier(Reader *reader, unsigned char tag) {
    unsigned char list_tag;
    Py_ssize_t length = 0;
    PyObject *list_obj = NULL;
    PyObject *result = NULL;

    if (!reader_ensure(reader, 1, "tag de lista modificado")) {
        return NULL;
    }
    list_tag = reader->data[reader->off++];
    if (list_tag == TAG_LIST_EMPTY) {
        list_obj = PyList_New(0);
        if (list_obj == NULL) {
            return NULL;
        }
    } else if (list_tag >= TAG_LIST1 && list_tag <= TAG_LIST4) {
        int n = (int)(list_tag - TAG_LIST_EMPTY);
        if (!reader_ensure(reader, n, "longitud de lista modificada")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de lista modificada")) {
            return NULL;
        }
        list_obj = parse_list_content(reader->data + reader->off, length);
        if (list_obj == NULL) {
            return NULL;
        }
        reader->off += length;
    } else {
        PyErr_Format(PyExc_ValueError, "fastbincodec: modificador 0x%02x seguido de tag inválido 0x%02x", tag, list_tag);
        return NULL;
    }

    result = wrap_sequence_modifier(tag, list_obj);
    Py_DECREF(list_obj);
    return result;
}

static PyObject *parse_struct_modifier(Reader *reader, unsigned char tag) {
    unsigned char map_tag;
    Py_ssize_t length = 0;
    PyObject *result;

    if (!reader_ensure(reader, 1, "tag de mapa struct")) {
        return NULL;
    }
    map_tag = reader->data[reader->off++];
    if (map_tag == TAG_MAP_EMPTY) {
        return PyDict_New();
    }
    if (map_tag < TAG_MAP1 || map_tag > TAG_MAP4) {
        PyErr_Format(PyExc_ValueError, "fastbincodec: modificador struct 0x%02x seguido de tag inválido 0x%02x", tag, map_tag);
        return NULL;
    }

    {
        int n = (int)(map_tag - TAG_MAP_EMPTY);
        if (!reader_ensure(reader, n, "longitud de mapa struct")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de mapa struct")) {
            return NULL;
        }
        result = parse_map_content(reader->data + reader->off, length);
        if (result == NULL) {
            return NULL;
        }
        reader->off += length;
    }

    return result;
}

static PyObject *parse_value(Reader *reader) {
    unsigned char tag;

    if (!reader_ensure(reader, 1, "tag")) {
        return NULL;
    }
    tag = reader->data[reader->off++];

    if (tag == TAG_NULL_VALUE || tag == TAG_BOOL_NONE) {
        Py_RETURN_NONE;
    }
    if (tag == TAG_BOOL_FALSE) {
        Py_RETURN_FALSE;
    }
    if (tag == TAG_BOOL_TRUE) {
        Py_RETURN_TRUE;
    }
    if (tag == TAG_INT0) {
        return PyLong_FromLong(0);
    }
    if (tag == TAG_INT_1) {
        return PyLong_FromLong(1);
    }
    if (tag == TAG_INT_NEG1) {
        return PyLong_FromLong(-1);
    }
    if (tag >= TAG_INT0 + 1 && tag <= TAG_INT_LAST) {
        int n = (int)(tag - TAG_INT0);
        int64_t value;
        if (!reader_ensure(reader, n, "entero con signo")) {
            return NULL;
        }
        value = read_int_be_raw(reader->data + reader->off, n);
        reader->off += n;
        return PyLong_FromLongLong((long long)value);
    }
    if (tag == TAG_UINT0) {
        return PyLong_FromLong(0);
    }
    if (tag == TAG_UINT_1) {
        return PyLong_FromLong(1);
    }
    if (tag >= TAG_UINT0 + 1 && tag <= TAG_UINT_LAST) {
        int n = (int)(tag - TAG_UINT0);
        uint64_t value;
        if (!reader_ensure(reader, n, "entero sin signo")) {
            return NULL;
        }
        value = read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        return PyLong_FromUnsignedLongLong((unsigned long long)value);
    }
    if (tag == TAG_FLOAT0) {
        return PyFloat_FromDouble(0.0);
    }
    if (tag == TAG_FLOAT1) {
        return PyFloat_FromDouble(1.0);
    }
    if (tag == TAG_FLOAT32) {
        union {
            uint32_t bits;
            float value;
        } number;
        if (!reader_ensure(reader, 4, "float32")) {
            return NULL;
        }
        number.bits = (uint32_t)read_uint_be_raw(reader->data + reader->off, 4);
        reader->off += 4;
        return PyFloat_FromDouble((double)number.value);
    }
    if (tag == TAG_FLOAT64) {
        union {
            uint64_t bits;
            double value;
        } number;
        if (!reader_ensure(reader, 8, "float64")) {
            return NULL;
        }
        number.bits = read_uint_be_raw(reader->data + reader->off, 8);
        reader->off += 8;
        return PyFloat_FromDouble(number.value);
    }
    if (tag >= TAG_STRING_SHORT_BASE && tag <= TAG_STRING_SHORT_MAX) {
        Py_ssize_t length = (Py_ssize_t)(tag - TAG_STRING_SHORT_BASE + 1);
        if (!reader_ensure(reader, length, "string corta")) {
            return NULL;
        }
        {
            PyObject *result = PyUnicode_DecodeUTF8((const char *)reader->data + reader->off, length, "strict");
            if (result == NULL) {
                return NULL;
            }
            reader->off += length;
            return result;
        }
    }
    if (tag == TAG_STRING_EMPTY) {
        return PyUnicode_FromStringAndSize("", 0);
    }
    if (tag == TAG_STRING_S) {
        return PyUnicode_FromStringAndSize("S", 1);
    }
    if (tag == TAG_STRING_N) {
        return PyUnicode_FromStringAndSize("N", 1);
    }
    if (tag >= TAG_STRING1 && tag <= TAG_STRING4) {
        int n = (int)(tag - TAG_STRING_EMPTY);
        Py_ssize_t length;
        if (!reader_ensure(reader, n, "longitud de string")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de string")) {
            return NULL;
        }
        {
            PyObject *result = PyUnicode_DecodeUTF8((const char *)reader->data + reader->off, length, "strict");
            if (result == NULL) {
                return NULL;
            }
            reader->off += length;
            return result;
        }
    }
    if (tag == TAG_BYTES_EMPTY || tag == TAG_RECORD_EMPTY) {
        return PyBytes_FromStringAndSize("", 0);
    }
    if ((tag >= TAG_BYTES1 && tag <= TAG_BYTES4) || (tag >= TAG_RECORD1 && tag <= TAG_RECORD4)) {
        int n = (int)((tag & 0xF0U) == 0x50U ? tag - TAG_BYTES_EMPTY : tag - TAG_RECORD_EMPTY);
        Py_ssize_t length;
        if (!reader_ensure(reader, n, "longitud de blob")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de blob")) {
            return NULL;
        }
        {
            PyObject *result = PyBytes_FromStringAndSize((const char *)reader->data + reader->off, length);
            if (result == NULL) {
                return NULL;
            }
            reader->off += length;
            return result;
        }
    }
    if (tag == TAG_LIST_EMPTY) {
        return PyList_New(0);
    }
    if (tag >= TAG_LIST1 && tag <= TAG_LIST4) {
        int n = (int)(tag - TAG_LIST_EMPTY);
        Py_ssize_t length;
        PyObject *result;
        if (!reader_ensure(reader, n, "longitud de lista")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de lista")) {
            return NULL;
        }
        result = parse_list_content(reader->data + reader->off, length);
        if (result == NULL) {
            return NULL;
        }
        reader->off += length;
        return result;
    }
    if (tag == TAG_MAP_EMPTY) {
        return PyDict_New();
    }
    if (tag >= TAG_MAP1 && tag <= TAG_MAP4) {
        int n = (int)(tag - TAG_MAP_EMPTY);
        Py_ssize_t length;
        PyObject *result;
        if (!reader_ensure(reader, n, "longitud de mapa")) {
            return NULL;
        }
        length = (Py_ssize_t)read_uint_be_raw(reader->data + reader->off, n);
        reader->off += n;
        if (!reader_ensure(reader, length, "contenido de mapa")) {
            return NULL;
        }
        result = parse_map_content(reader->data + reader->off, length);
        if (result == NULL) {
            return NULL;
        }
        reader->off += length;
        return result;
    }
    if (tag == TAG_DATE_EMPTY || tag == TAG_DATETIME_EMPTY) {
        return PyLong_FromLong(0);
    }
    if (tag == TAG_DATE || tag == TAG_TIME) {
        uint64_t value;
        if (!reader_ensure(reader, 3, "fecha/hora")) {
            return NULL;
        }
        value = read_uint_be_raw(reader->data + reader->off, 3);
        reader->off += 3;
        return PyLong_FromUnsignedLongLong((unsigned long long)value);
    }
    if (tag == TAG_DATETIME) {
        uint64_t value;
        if (!reader_ensure(reader, 5, "datetime")) {
            return NULL;
        }
        value = read_uint_be_raw(reader->data + reader->off, 5);
        reader->off += 5;
        return PyLong_FromUnsignedLongLong((unsigned long long)value);
    }
    if (tag == TAG_TIME_EMPTY) {
        return PyLong_FromUnsignedLong(TIME_NONE);
    }
    if (tag == TAG_TUPLE_MOD || tag == TAG_SET_MOD || tag == TAG_FROZENSET_MOD) {
        return parse_collection_modifier(reader, tag);
    }
    if (tag == TAG_STRUCT_MAP_MOD || tag == TAG_STRUCT_LIST_MOD) {
        return parse_struct_modifier(reader, tag);
    }

    PyErr_Format(PyExc_ValueError, "fastbincodec: tag desconocido 0x%02x en offset %zd", tag, reader->off - 1);
    return NULL;
}

static PyObject *fastbincodec_decode_record(PyObject *self, PyObject *arg) {
    Py_buffer view;
    Reader reader;
    PyObject *result;

    (void)self;

    if (PyObject_GetBuffer(arg, &view, PyBUF_SIMPLE) < 0) {
        return NULL;
    }

    reader.data = (const unsigned char *)view.buf;
    reader.len = view.len;
    reader.off = 0;

    result = PyList_New(0);
    if (result == NULL) {
        PyBuffer_Release(&view);
        return NULL;
    }

    while (reader.off < reader.len) {
        PyObject *value;

        if (!reader_ensure(&reader, 1, "tag raíz")) {
            Py_DECREF(result);
            PyBuffer_Release(&view);
            return NULL;
        }

        if (reader.data[reader.off] == TAG_SKIP) {
            if (!reader_ensure(&reader, 2, "TAG_SKIP")) {
                Py_DECREF(result);
                PyBuffer_Release(&view);
                return NULL;
            }
            reader.off += 2;
            continue;
        }

        value = parse_value(&reader);
        if (value == NULL) {
            Py_DECREF(result);
            PyBuffer_Release(&view);
            return NULL;
        }
        if (PyList_Append(result, value) < 0) {
            Py_DECREF(value);
            Py_DECREF(result);
            PyBuffer_Release(&view);
            return NULL;
        }
        Py_DECREF(value);
    }

    PyBuffer_Release(&view);
    return result;
}

static PyObject *fastbincodec_project_record_len_select_246(PyObject *self, PyObject *arg) {
    (void)self;
    return project_record_length_common(arg, 0);
}

static PyObject *fastbincodec_project_record_len_select_246_list2(PyObject *self, PyObject *arg) {
    (void)self;
    return project_record_length_common(arg, 1);
}

static PyMethodDef fastbincodec_methods[] = {
    {
        "decode_record",
        (PyCFunction)fastbincodec_decode_record,
        METH_O,
        PyDoc_STR("decode_record(payload) -> list\n\nDecodifica el payload bincodec completo de un registro a valores Python nativos."),
    },
    {
        "project_record_len_select_246",
        (PyCFunction)fastbincodec_project_record_len_select_246,
        METH_O,
        PyDoc_STR("project_record_len_select_246(payload) -> int\n\nRecorre el payload y reserializa en un buffer interno solo los campos 2, 4 y 6; devuelve los bytes producidos."),
    },
    {
        "project_record_len_select_246_list2",
        (PyCFunction)fastbincodec_project_record_len_select_246_list2,
        METH_O,
        PyDoc_STR("project_record_len_select_246_list2(payload) -> int\n\nRecorre el payload y reserializa en un buffer interno los campos 2, 4 y 6 más el segundo elemento de la lista del campo 7; devuelve los bytes producidos."),
    },
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef fastbincodec_module = {
    PyModuleDef_HEAD_INIT,
    "fastbincodec",
    "Extensión C mínima para decode completo de registros bincodec.",
    -1,
    fastbincodec_methods,
    NULL,
    NULL,
    NULL,
    NULL
};

PyMODINIT_FUNC PyInit_fastbincodec(void) {
    return PyModule_Create(&fastbincodec_module);
}