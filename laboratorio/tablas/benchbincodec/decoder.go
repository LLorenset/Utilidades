package benchbincodec

/*
================================================================================
BENCHBINCODEC / DECODIFICADOR LOCAL PARA BENCHMARK
================================================================================

Responsabilidad:
  Reproducir dentro del módulo de benchmarks el recorrido real del payload
  bincodec para poder medir el coste de deserialización de valores Pebble.

Diseño:
  - Este paquete existe porque el benchmark vive en un módulo separado y no
    puede importar los paquetes internal del servidor.
  - Implementa un decoder autónomo que recorre y materializa valores
    suficientes para que la medición incluya parseo recursivo, strings, listas,
    mapas, números y blobs.
	- También expone una proyección cruda que no materializa `Value`: recorre el
		payload, localiza spans bincodec ya serializados y reemite solo el
		subconjunto seleccionado para simular un `SELECT` parcial.
  - El objetivo no es exponer una API de negocio, sino sumar al benchmark el
    trabajo CPU del decoder de forma estable y verificable.

Invariantes:
  - El payload recibido ya viene sin la cabecera [ctrl][version].
  - La compresión del experimento está en SST, no en el registro individual.
  - Si aparece un tag desconocido o un dato truncado, se devuelve error.
================================================================================
*/

import (
	"encoding/binary"
	"fmt"
	"math"
)

const (
	tagSkip            = 0x09
	tagRecordEmpty     = 0x10
	tagRecord1         = 0x11
	tagRecord4         = 0x14
	tagListEmpty       = 0x20
	tagList1           = 0x21
	tagList4           = 0x24
	tagTupleMod        = 0x25
	tagSetMod          = 0x26
	tagFrozenSetMod    = 0x27
	tagStringShortBase = 0x30
	tagStringShortMax  = 0x3F
	tagStringEmpty     = 0x40
	tagString1         = 0x41
	tagString4         = 0x44
	tagStringS         = 0x45
	tagStringN         = 0x46
	tagBytesEmpty      = 0x50
	tagBytes1          = 0x51
	tagBytes4          = 0x54
	tagInt0            = 0x60
	tagInt1            = 0x61
	tagInt8            = 0x68
	tagIntP1           = 0x69
	tagIntN1           = 0x6A
	tagUint0           = 0x70
	tagUint1           = 0x71
	tagUint8           = 0x78
	tagUintP1          = 0x79
	tagFloat0          = 0x80
	tagFloat32         = 0x84
	tagFloat64         = 0x88
	tagFloatP1         = 0x89
	tagDateEmpty       = 0x90
	tagDate            = 0x91
	tagDateTimeEmpty   = 0x92
	tagDateTime        = 0x93
	tagTimeNone        = 0x94
	tagTime            = 0x95
	tagMapEmpty        = 0xA0
	tagMap1            = 0xA1
	tagMap4            = 0xA4
	tagNullValue       = 0xA5
	tagStructMapMod    = 0xA8
	tagStructListMod   = 0xA9
	tagBoolNone        = 0xB0
	tagBoolFalse       = 0xB1
	tagBoolTrue        = 0xB2
)

// ProjectionProfile identifica una proyección fija de campos del registro HI.
type ProjectionProfile string

type projectionState struct {
	found2     bool
	found4     bool
	found6     bool
	foundList2 bool
}

const (
	// ProjectionSelect246 reemite los campos 2, 4 y 6 del registro raíz.
	ProjectionSelect246 ProjectionProfile = "select_246"
	// ProjectionSelect246List2 reemite los campos 2, 4 y 6 más el segundo valor
	// de la lista del campo raíz 7.
	ProjectionSelect246List2 ProjectionProfile = "select_246_list2"
)

// Value materializa de forma mínima un valor decodificado para forzar el coste
// normal de deserialización durante el benchmark.
type Value struct {
	RawInt   int64
	RawFloat float64
	Str      string
	Bytes    []byte
	List     []Value
	Map      map[string]Value
	Bool     bool
}

// DecodePayload recorre el payload bincodec completo y valida que todos los
// campos puedan deserializarse sin truncados ni tags desconocidos.
func DecodePayload(payload []byte) error {
	offset := 0
	for offset < len(payload) {
		next, _, err := decodeValue(payload, offset)
		if err != nil {
			return err
		}
		if next <= offset {
			return fmt.Errorf("bincodec benchmark: avance no válido offset=%d next=%d", offset, next)
		}
		offset = next
	}
	return nil
}

// Valid valida que el perfil de proyección sea uno de los soportados.
func (p ProjectionProfile) Valid() bool {
	switch p {
	case ProjectionSelect246, ProjectionSelect246List2:
		return true
	default:
		return false
	}
}

// ProjectPayload recorre el payload sin materializar valores y reemite una
// versión reducida concatenando los campos seleccionados en formato bincodec.
func ProjectPayload(payload []byte, profile ProjectionProfile, dst []byte) ([]byte, error) {
	if !profile.Valid() {
		return nil, fmt.Errorf("bincodec benchmark: perfil de proyección no soportado %q", profile)
	}

	result := dst[:0]
	offset := 0
	fieldIndex := 0
	state := newProjectionState(profile)

	for offset < len(payload) {
		if payload[offset] == tagSkip {
			if offset+1 >= len(payload) {
				return nil, fmt.Errorf("bincodec benchmark: skip truncado en offset %d", offset)
			}
			offset += 2
			continue
		}

		start := offset
		next, err := skipValue(payload, offset)
		if err != nil {
			return nil, err
		}
		fieldIndex++
		result, err = state.collectField(payload, fieldIndex, start, next, profile, result)
		if err != nil {
			return nil, err
		}

		offset = next
	}

	return state.appendMissing(result, profile), nil
}

func newProjectionState(profile ProjectionProfile) projectionState {
	return projectionState{foundList2: profile != ProjectionSelect246List2}
}

func (s *projectionState) collectField(payload []byte, fieldIndex int, start int, next int, profile ProjectionProfile, dst []byte) ([]byte, error) {
	switch fieldIndex {
	case 2:
		s.found2 = true
		return append(dst, payload[start:next]...), nil
	case 4:
		s.found4 = true
		return append(dst, payload[start:next]...), nil
	case 6:
		s.found6 = true
		return append(dst, payload[start:next]...), nil
	case 7:
		if profile != ProjectionSelect246List2 {
			return dst, nil
		}
		projected, found, err := appendSecondListItem(payload, start, dst)
		if err != nil {
			return nil, err
		}
		s.foundList2 = found
		return projected, nil
	default:
		return dst, nil
	}
}

func (s projectionState) appendMissing(dst []byte, profile ProjectionProfile) []byte {
	if !s.found2 {
		dst = appendNullValue(dst)
	}
	if !s.found4 {
		dst = appendNullValue(dst)
	}
	if !s.found6 {
		dst = appendNullValue(dst)
	}
	if profile == ProjectionSelect246List2 && !s.foundList2 {
		dst = appendNullValue(dst)
	}
	return dst
}

func decodeValue(raw []byte, offset int) (int, Value, error) {
	if offset >= len(raw) {
		return offset, Value{}, fmt.Errorf("bincodec benchmark: offset %d fuera de rango", offset)
	}
	tag := raw[offset]
	offset++

	switch {
	case tag == tagSkip:
		if offset >= len(raw) {
			return 0, Value{}, fmt.Errorf("bincodec benchmark: skip truncado")
		}
		return offset + 1, Value{}, nil
	case tag == tagListEmpty:
		return offset, Value{List: nil}, nil
	case tag >= tagList1 && tag <= tagList4:
		inner, next, err := readBlob(raw, offset, int(tag-tagListEmpty))
		if err != nil {
			return 0, Value{}, err
		}
		list, err := decodeList(inner)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{List: list}, nil
	case tag == tagTupleMod || tag == tagSetMod || tag == tagFrozenSetMod:
		return decodeValue(raw, offset)
	case tag >= tagStringShortBase && tag <= tagStringShortMax:
		length := int(tag-tagStringShortBase) + 1
		if offset+length > len(raw) {
			return 0, Value{}, fmt.Errorf("bincodec benchmark: string short truncado")
		}
		return offset + length, Value{Str: string(raw[offset : offset+length])}, nil
	case tag == tagStringEmpty:
		return offset, Value{Str: ""}, nil
	case tag >= tagString1 && tag <= tagString4:
		inner, next, err := readBlob(raw, offset, int(tag-tagStringEmpty))
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{Str: string(inner)}, nil
	case tag == tagStringS:
		return offset, Value{Str: "S"}, nil
	case tag == tagStringN:
		return offset, Value{Str: "N"}, nil
	case tag == tagBytesEmpty:
		return offset, Value{Bytes: nil}, nil
	case tag >= tagBytes1 && tag <= tagBytes4:
		inner, next, err := readBlob(raw, offset, int(tag-tagBytesEmpty))
		if err != nil {
			return 0, Value{}, err
		}
		copied := append([]byte(nil), inner...)
		return next, Value{Bytes: copied}, nil
	case tag == tagInt0:
		return offset, Value{RawInt: 0}, nil
	case tag == tagIntP1:
		return offset, Value{RawInt: 1}, nil
	case tag == tagIntN1:
		return offset, Value{RawInt: -1}, nil
	case tag >= tagInt1 && tag <= tagInt8:
		size := int(tag - tagInt0)
		value, next, err := readSigned(raw, offset, size)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{RawInt: value}, nil
	case tag == tagUint0:
		return offset, Value{RawInt: 0}, nil
	case tag == tagUintP1:
		return offset, Value{RawInt: 1}, nil
	case tag >= tagUint1 && tag <= tagUint8:
		size := int(tag - tagUint0)
		value, next, err := readUnsigned(raw, offset, size)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{RawInt: int64(value)}, nil
	case tag == tagFloat0:
		return offset, Value{RawFloat: 0}, nil
	case tag == tagFloatP1:
		return offset, Value{RawFloat: 1}, nil
	case tag == tagFloat32:
		if offset+4 > len(raw) {
			return 0, Value{}, fmt.Errorf("bincodec benchmark: float32 truncado")
		}
		bits := binary.BigEndian.Uint32(raw[offset : offset+4])
		return offset + 4, Value{RawFloat: float64(math.Float32frombits(bits))}, nil
	case tag == tagFloat64:
		if offset+8 > len(raw) {
			return 0, Value{}, fmt.Errorf("bincodec benchmark: float64 truncado")
		}
		bits := binary.BigEndian.Uint64(raw[offset : offset+8])
		return offset + 8, Value{RawFloat: math.Float64frombits(bits)}, nil
	case tag == tagDateEmpty || tag == tagDateTimeEmpty || tag == tagTimeNone || tag == tagBoolNone || tag == tagNullValue:
		return offset, Value{}, nil
	case tag == tagDate || tag == tagTime:
		value, next, err := readSigned(raw, offset, 3)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{RawInt: value}, nil
	case tag == tagDateTime:
		value, next, err := readSigned(raw, offset, 5)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{RawInt: value}, nil
	case tag == tagMapEmpty:
		return offset, Value{Map: nil}, nil
	case tag >= tagMap1 && tag <= tagMap4:
		inner, next, err := readBlob(raw, offset, int(tag-tagMapEmpty))
		if err != nil {
			return 0, Value{}, err
		}
		mapped, err := decodeMap(inner)
		if err != nil {
			return 0, Value{}, err
		}
		return next, Value{Map: mapped}, nil
	case tag == tagStructMapMod || tag == tagStructListMod:
		return decodeValue(raw, offset)
	case tag == tagBoolFalse:
		return offset, Value{Bool: false}, nil
	case tag == tagBoolTrue:
		return offset, Value{Bool: true}, nil
	default:
		return 0, Value{}, fmt.Errorf("bincodec benchmark: tag desconocido 0x%02x", tag)
	}
}

func decodeList(content []byte) ([]Value, error) {
	list := make([]Value, 0)
	offset := 0
	for offset < len(content) {
		next, value, err := decodeValue(content, offset)
		if err != nil {
			return nil, err
		}
		list = append(list, value)
		offset = next
	}
	return list, nil
}

func decodeMap(content []byte) (map[string]Value, error) {
	result := make(map[string]Value)
	offset := 0
	for offset < len(content) {
		next, keyValue, err := decodeValue(content, offset)
		if err != nil {
			return nil, err
		}
		offset = next
		next, value, err := decodeValue(content, offset)
		if err != nil {
			return nil, err
		}
		result[keyValue.Str] = value
		offset = next
	}
	return result, nil
}

func appendSecondListItem(payload []byte, start int, dst []byte) ([]byte, bool, error) {
	if start >= len(payload) {
		return nil, false, fmt.Errorf("bincodec benchmark: offset %d fuera de rango en lista proyectada", start)
	}

	tag := payload[start]
	offset := start + 1
	for tag == tagTupleMod || tag == tagSetMod || tag == tagFrozenSetMod {
		if offset >= len(payload) {
			return nil, false, fmt.Errorf("bincodec benchmark: modificador de colección truncado en offset %d", start)
		}
		tag = payload[offset]
		offset++
	}

	if tag == tagListEmpty {
		return appendNullValue(dst), true, nil
	}
	if tag < tagList1 || tag > tagList4 {
		return nil, false, fmt.Errorf("bincodec benchmark: se esperaba lista en campo 7 y llegó tag 0x%02x", tag)
	}

	lenBytes := int(tag - tagListEmpty)
	length, err := readLenBE(payload, offset, lenBytes)
	if err != nil {
		return nil, false, err
	}
	contentStart := offset + lenBytes
	contentEnd := contentStart + length
	if contentEnd > len(payload) {
		return nil, false, fmt.Errorf("bincodec benchmark: lista proyectada truncada")
	}

	itemIndex := 0
	innerOffset := contentStart
	for innerOffset < contentEnd {
		itemStart := innerOffset
		next, err := skipValue(payload, innerOffset)
		if err != nil {
			return nil, false, err
		}
		itemIndex++
		if itemIndex == 2 {
			return append(dst, payload[itemStart:next]...), true, nil
		}
		innerOffset = next
	}

	return appendNullValue(dst), true, nil
}

func appendNullValue(dst []byte) []byte {
	return append(dst, tagNullValue)
}

func skipValue(raw []byte, offset int) (int, error) {
	if offset >= len(raw) {
		return 0, fmt.Errorf("bincodec benchmark: offset %d fuera de rango", offset)
	}
	tag := raw[offset]
	offset++

	if tag == tagSkip {
		if offset >= len(raw) {
			return 0, fmt.Errorf("bincodec benchmark: skip truncado")
		}
		return offset + 1, nil
	}
	if isImmediateTag(tag) {
		return offset, nil
	}
	if isShortStringTag(tag) {
		return skipShortString(raw, offset, tag)
	}
	if end, handled, err := skipLengthPrefixedTag(raw, offset, tag); handled {
		return end, err
	}
	if end, handled, err := skipFixedWidthTag(raw, offset, tag); handled {
		return end, err
	}
	if isModifierTag(tag) {
		return skipValue(raw, offset)
	}
	return 0, fmt.Errorf("bincodec benchmark: tag desconocido 0x%02x", tag)
}

func isImmediateTag(tag byte) bool {
	switch tag {
	case tagRecordEmpty, tagBytesEmpty, tagStringEmpty, tagStringS, tagStringN,
		tagListEmpty, tagMapEmpty,
		tagInt0, tagIntP1, tagIntN1,
		tagUint0, tagUintP1,
		tagFloat0, tagFloatP1,
		tagDateEmpty, tagDateTimeEmpty, tagTimeNone, tagBoolNone, tagNullValue,
		tagBoolFalse, tagBoolTrue:
		return true
	default:
		return false
	}
}

func isShortStringTag(tag byte) bool {
	return tag >= tagStringShortBase && tag <= tagStringShortMax
}

func skipShortString(raw []byte, offset int, tag byte) (int, error) {
	length := int(tag-tagStringShortBase) + 1
	if offset+length > len(raw) {
		return 0, fmt.Errorf("bincodec benchmark: string short truncado")
	}
	return offset + length, nil
}

func skipLengthPrefixedTag(raw []byte, offset int, tag byte) (int, bool, error) {
	var end int
	var err error

	switch {
	case tag >= tagString1 && tag <= tagString4:
		end, err = skipBlob(raw, offset, int(tag-tagStringEmpty))
		return end, true, err
	case tag >= tagBytes1 && tag <= tagBytes4:
		end, err = skipBlob(raw, offset, int(tag-tagBytesEmpty))
		return end, true, err
	case tag >= tagRecord1 && tag <= tagRecord4:
		end, err = skipBlob(raw, offset, int(tag-tagRecordEmpty))
		return end, true, err
	case tag >= tagList1 && tag <= tagList4:
		end, err = skipBlob(raw, offset, int(tag-tagListEmpty))
		return end, true, err
	case tag >= tagMap1 && tag <= tagMap4:
		end, err = skipBlob(raw, offset, int(tag-tagMapEmpty))
		return end, true, err
	default:
		return 0, false, nil
	}
}

func skipFixedWidthTag(raw []byte, offset int, tag byte) (int, bool, error) {
	var end int
	var err error

	switch {
	case tag >= tagInt1 && tag <= tagInt8:
		end, err = skipFixed(raw, offset, int(tag-tagInt0), "entero con signo")
		return end, true, err
	case tag >= tagUint1 && tag <= tagUint8:
		end, err = skipFixed(raw, offset, int(tag-tagUint0), "entero sin signo")
		return end, true, err
	case tag == tagFloat32:
		end, err = skipFixed(raw, offset, 4, "float32")
		return end, true, err
	case tag == tagFloat64:
		end, err = skipFixed(raw, offset, 8, "float64")
		return end, true, err
	case tag == tagDate || tag == tagTime:
		end, err = skipFixed(raw, offset, 3, "fecha/hora")
		return end, true, err
	case tag == tagDateTime:
		end, err = skipFixed(raw, offset, 5, "datetime")
		return end, true, err
	default:
		return 0, false, nil
	}
}

func isModifierTag(tag byte) bool {
	return tag == tagTupleMod || tag == tagSetMod || tag == tagFrozenSetMod || tag == tagStructMapMod || tag == tagStructListMod
}

func skipBlob(raw []byte, offset int, lenBytes int) (int, error) {
	length, err := readLenBE(raw, offset, lenBytes)
	if err != nil {
		return 0, err
	}
	start := offset + lenBytes
	end := start + length
	if end > len(raw) {
		return 0, fmt.Errorf("bincodec benchmark: blob truncado")
	}
	return end, nil
}

func skipFixed(raw []byte, offset int, size int, label string) (int, error) {
	if offset+size > len(raw) {
		return 0, fmt.Errorf("bincodec benchmark: %s truncado", label)
	}
	return offset + size, nil
}

func readBlob(raw []byte, offset int, lenBytes int) ([]byte, int, error) {
	length, err := readLenBE(raw, offset, lenBytes)
	if err != nil {
		return nil, 0, err
	}
	start := offset + lenBytes
	end := start + length
	if end > len(raw) {
		return nil, 0, fmt.Errorf("bincodec benchmark: blob truncado")
	}
	return raw[start:end], end, nil
}

func readLenBE(raw []byte, offset int, size int) (int, error) {
	value, _, err := readUnsigned(raw, offset, size)
	if err != nil {
		return 0, err
	}
	return int(value), nil
}

func readUnsigned(raw []byte, offset int, size int) (uint64, int, error) {
	if offset+size > len(raw) {
		return 0, 0, fmt.Errorf("bincodec benchmark: entero truncado")
	}
	var value uint64
	for index := 0; index < size; index++ {
		value = value<<8 | uint64(raw[offset+index])
	}
	return value, offset + size, nil
}

func readSigned(raw []byte, offset int, size int) (int64, int, error) {
	unsigned, next, err := readUnsigned(raw, offset, size)
	if err != nil {
		return 0, 0, err
	}
	value := int64(unsigned)
	bits := uint(size * 8)
	sign := int64(1) << (bits - 1)
	if value >= sign {
		value -= sign << 1
	}
	return value, next, nil
}
