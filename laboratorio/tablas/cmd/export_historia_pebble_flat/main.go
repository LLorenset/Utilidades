package main
package main

/*
==== Responsabilidad

Este script exporta los payloads bincodec de la tabla HI en Pebble a un fichero
binario plano con framing por longitud, para medir luego en Python el coste
puro de deserialización sin ruido del motor Pebble.

==== Flujo

1. Abre la base Pebble en solo lectura.
2. Recorre el keyspace HI completo por prefijo.
3. Extrae de cada value la parte [data], saltando [ctrl][version].
4. Escribe cada payload como [len uint32 BE][payload bytes].
5. Genera un JSON lateral con el resumen de la exportación.

==== Diseño

- El fichero plano usa uint32 big-endian + payload para simplificar la lectura
  desde Python.
- Se exporta solo el payload bincodec, no la cabecera fija del record, porque
  la comparación busca aislar el coste del decoder frente a pickle.
- La compresión SST ya ha sido resuelta por Pebble al leer; aquí no hay trabajo
  adicional de compresión por registro.
*/

import (
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"

	"github.com/cockroachdb/pebble/v2"
)

var exportHistoriaPrefix = []byte{0x01, 'H', 'I', 0x00}

type exportConfig struct {
	pebblePath string
	outputPath string
	metaJSON   string
	limit      int
}

type exportMeta struct {
	Engine          string `json:"engine"`
	SourcePath      string `json:"source_path"`
	Records         int    `json:"records"`
	PayloadBytes    int    `json:"payload_bytes"`
	MinPayloadBytes int    `json:"min_payload_bytes"`
	MaxPayloadBytes int    `json:"max_payload_bytes"`
	FlatFile        string `json:"flat_file"`
	Limit           int    `json:"limit"`
}

func parseExportConfig() exportConfig {
	conf := exportConfig{}
	flag.StringVar(&conf.pebblePath, "pebble-path", filepath.Join(".", "pebbleHINoComp"), "Ruta del directorio Pebble a exportar")
	flag.StringVar(&conf.outputPath, "output-path", "historia_pebble_payloads.flatbin", "Ruta del fichero plano de salida")
	flag.StringVar(&conf.metaJSON, "meta-json", "", "Ruta opcional del JSON resumen")
	flag.IntVar(&conf.limit, "limit", 0, "Máximo de registros a exportar. 0 = sin límite")
	flag.Parse()
	return conf
}

func (c exportConfig) validate() error {
	if c.limit < 0 {
		return fmt.Errorf("limit no puede ser negativo")
	}
	return nil
}

func openExportDB(path string) (*pebble.DB, error) {
	return pebble.Open(path, &pebble.Options{ReadOnly: true})
}

func nextExportPrefix(prefix []byte) []byte {
	out := append([]byte(nil), prefix...)
	for index := len(out) - 1; index >= 0; index-- {
		if out[index] != 0xFF {
			out[index]++
			return out[:index+1]
		}
	}
	return nil
}

func resolveMetaJSON(outputPath string, explicit string) string {
	if explicit != "" {
		return explicit
	}
	return outputPath + ".json"
}

func writeFlatRecord(file *os.File, payload []byte) error {
	var length [4]byte
	binary.BigEndian.PutUint32(length[:], uint32(len(payload)))
	if _, err := file.Write(length[:]); err != nil {
		return err
	}
	_, err := file.Write(payload)
	return err
}

func exportPayloads(db *pebble.DB, conf exportConfig) (exportMeta, error) {
	iter, err := db.NewIter(&pebble.IterOptions{
		LowerBound: exportHistoriaPrefix,
		UpperBound: nextExportPrefix(exportHistoriaPrefix),
	})
	if err != nil {
		return exportMeta{}, err
	}
	defer func() {
		_ = iter.Close()
	}()

	if err := os.MkdirAll(filepath.Dir(conf.outputPath), 0o755); err != nil && filepath.Dir(conf.outputPath) != "." {
		return exportMeta{}, err
	}
	file, err := os.Create(conf.outputPath)
	if err != nil {
		return exportMeta{}, err
	}
	defer func() {
		_ = file.Close()
	}()

	meta := exportMeta{
		Engine:     "pebble",
		SourcePath: conf.pebblePath,
		FlatFile:   conf.outputPath,
		Limit:      conf.limit,
	}
	minLength := -1

	for iter.First(); iter.Valid(); iter.Next() {
		value := iter.Value()
		if len(value) < 5 {
			return exportMeta{}, fmt.Errorf("value truncado para key %q: %d bytes", string(iter.Key()), len(value))
		}
		payload := append([]byte(nil), value[5:]...)
		if err := writeFlatRecord(file, payload); err != nil {
			return exportMeta{}, err
		}
		payloadLength := len(payload)
		meta.PayloadBytes += payloadLength
		if payloadLength > meta.MaxPayloadBytes {
			meta.MaxPayloadBytes = payloadLength
		}
		if minLength == -1 || payloadLength < minLength {
			minLength = payloadLength
		}
		meta.Records++
		if conf.limit > 0 && meta.Records >= conf.limit {
			break
		}
	}
	if err := iter.Error(); err != nil {
		return exportMeta{}, err
	}
	if minLength >= 0 {
		meta.MinPayloadBytes = minLength
	}
	return meta, nil
}

func writeExportMeta(meta exportMeta, metaPath string) error {
	if err := os.MkdirAll(filepath.Dir(metaPath), 0o755); err != nil && filepath.Dir(metaPath) != "." {
		return err
	}
	data, err := json.MarshalIndent(meta, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(metaPath, data, 0o644)
}

func main() {
	conf := parseExportConfig()
	if err := conf.validate(); err != nil {
		panic(err)
	}
	db, err := openExportDB(conf.pebblePath)
	if err != nil {
		panic(err)
	}
	defer func() {
		_ = db.Close()
	}()

	meta, err := exportPayloads(db, conf)
	if err != nil {
		panic(err)
	}
	metaPath := resolveMetaJSON(conf.outputPath, conf.metaJSON)
	if err := writeExportMeta(meta, metaPath); err != nil {
		panic(err)
	}

	fmt.Printf("Exportación Pebble completada: registros=%d bytes=%d\n", meta.Records, meta.PayloadBytes)
	fmt.Printf("Plano: %s\n", conf.outputPath)
	fmt.Printf("Meta: %s\n", metaPath)
}