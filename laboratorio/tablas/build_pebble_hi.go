package main

/*
==== Responsabilidad

Este script crea dos variantes Pebble reducidas al keyspace HI a partir de la
base `pebble` original: una con compresion Snappy y otra sin compresion.

==== Flujo

1. Abre la Pebble origen en solo lectura.
2. Recorre exclusivamente el rango [0x01]['H']['I'][0x00]...
3. Inserta todas las entradas en dos bases destino independientes.
4. Fuerza flush y compactacion para materializar SST con la compresion elegida.

==== Diseño

- No transforma ni recomprime registros individualmente; copia claves y valores
  tal cual y delega la diferencia al nivel SST del motor.
- El destino `pebbleHIcomp` usa Snappy, alineado con el comportamiento habitual
  de Pebble en disco.
- El destino `pebbleHINoComp` usa NoCompression para comparar contra el mismo
  keyspace sin coste de compresion de SST.
*/

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"slices"

	"github.com/cockroachdb/pebble/v2"
	"github.com/cockroachdb/pebble/v2/sstable"
)

var hiPrefix = []byte{0x01, 'H', 'I', 0x00}

type targetSpec struct {
	name        string
	path        string
	compression *sstable.CompressionProfile
}

// nextPrefix calcula el upper bound exclusivo para el prefijo HI.
func nextPrefix(prefix []byte) []byte {
	limit := slices.Clone(prefix)
	for index := len(limit) - 1; index >= 0; index-- {
		if limit[index] == 0xFF {
			continue
		}
		limit[index]++
		return limit[:index+1]
	}
	return nil
}

// makeOptions construye opciones Pebble con la compresion deseada en todos los niveles.
func makeOptions(compression *sstable.CompressionProfile) *pebble.Options {
	opts := &pebble.Options{}
	for index := range opts.Levels {
		opts.Levels[index].Compression = func() *sstable.CompressionProfile {
			return compression
		}
	}
	return opts
}

// recreateDir elimina y recrea un directorio destino para evitar mezcla de SST antiguas.
func recreateDir(path string) error {
	if err := os.RemoveAll(path); err != nil {
		return err
	}
	return os.MkdirAll(path, 0o755)
}

// copyHIEntries replica todas las entradas HI desde la base origen a la base destino.
func copyHIEntries(source *pebble.DB, target *pebble.DB) (int, error) {
	iter, err := source.NewIter(&pebble.IterOptions{
		LowerBound: hiPrefix,
		UpperBound: nextPrefix(hiPrefix),
	})
	if err != nil {
		return 0, err
	}
	defer func() {
		_ = iter.Close()
	}()

	rows := 0
	batch := target.NewBatch()
	defer func() {
		_ = batch.Close()
	}()

	for iter.First(); iter.Valid(); iter.Next() {
		key := slices.Clone(iter.Key())
		value := slices.Clone(iter.Value())
		if err := batch.Set(key, value, nil); err != nil {
			return 0, err
		}
		rows++
	}
	if err := iter.Error(); err != nil {
		return 0, err
	}
	if err := batch.Commit(pebble.Sync); err != nil {
		return 0, err
	}
	if err := target.Flush(); err != nil {
		return 0, err
	}
	if err := target.Compact(context.Background(), hiPrefix, nextPrefix(hiPrefix), true); err != nil {
		return 0, err
	}
	return rows, nil
}

// buildTarget crea una base destino con la compresion pedida y vuelca el keyspace HI.
func buildTarget(source *pebble.DB, spec targetSpec) error {
	if err := recreateDir(spec.path); err != nil {
		return fmt.Errorf("recrear %s: %w", spec.path, err)
	}
	target, err := pebble.Open(spec.path, makeOptions(spec.compression))
	if err != nil {
		return fmt.Errorf("abrir destino %s: %w", spec.path, err)
	}
	defer func() {
		_ = target.Close()
	}()

	rows, err := copyHIEntries(source, target)
	if err != nil {
		return fmt.Errorf("copiar HI a %s: %w", spec.path, err)
	}
	fmt.Printf("Creado %s en %s con %d registros HI\n", spec.name, spec.path, rows)
	return nil
}

func main() {
	baseDir := "."
	sourcePath := filepath.Join(baseDir, "pebble")
	targets := []targetSpec{
		{name: "pebbleHIcomp", path: filepath.Join(baseDir, "pebbleHIcomp"), compression: sstable.SnappyCompression},
		{name: "pebbleHINoComp", path: filepath.Join(baseDir, "pebbleHINoComp"), compression: sstable.NoCompression},
	}

	source, err := pebble.Open(sourcePath, &pebble.Options{ReadOnly: true})
	if err != nil {
		panic(fmt.Errorf("abrir origen %s: %w", sourcePath, err))
	}
	defer func() {
		_ = source.Close()
	}()

	for _, spec := range targets {
		if err := buildTarget(source, spec); err != nil {
			panic(err)
		}
	}
}
