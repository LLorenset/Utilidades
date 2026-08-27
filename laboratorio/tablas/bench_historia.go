package main

/*
==== Responsabilidad

Este script mide el coste de recorrer la tabla `historia` dentro de Pebble y
el coste de hacer lecturas aleatorias sobre llaves de esa misma tabla.

==== Flujo

1. Abre la base Pebble en solo lectura.
2. Recorre la tabla HI completa N veces usando el prefijo wire.
3. Guarda las llaves completas en la primera pasada.
4. Ejecuta M rondas de lectura aleatoria de X llaves y toma tiempos.
5. Permite comparar solo llaves frente a llaves+valores.
6. Puede añadir el coste de deserialización bincodec sobre el payload real.

==== Diseño

- La tabla HI se detecta por el prefijo [0x01]['H']['I'][0x00].
- Se guardan las llaves completas para que el acceso aleatorio use `Get`
  directamente sin recomponer claves.
- La primera pasada se presenta separada porque suele incluir calentamiento de
  cache y apertura real de estructuras del motor.
- En modo `keys`, las lecturas puntuales usan `SeekGE` sin tocar el valor.
- En modo `decoded`, cada value recorre el payload bincodec tras saltar
	la cabecera fija [ctrl][version].
*/

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"slices"
	"time"

	"utilidades/laboratorio/tablas/benchbincodec"

	"github.com/cockroachdb/pebble/v2"
)

var historiaPrefix = []byte{0x01, 'H', 'I', 0x00}

const (
	defaultJSONPath = "bench_historia_pebble.json"
	defaultCSVPath  = "bench_historia_pebble.csv"
)

type config struct {
	pebblePath      string
	scanPasses      int
	randomPasses    int
	randomKeys      int
	seed            int64
	readMode        string
	deserializeMode string
	outputJSON      string
	outputCSV       string
}

type scanMetrics struct {
	Pass           int     `json:"pass"`
	Seconds        float64 `json:"seconds"`
	Rows           int     `json:"rows"`
	TotalBytes     int     `json:"bytes"`
	RowsPerSecond  float64 `json:"rows_per_second"`
	BytesPerSecond float64 `json:"bytes_per_second"`
	keys           [][]byte
}

type randomMetrics struct {
	Pass           int     `json:"pass"`
	Requested      int     `json:"requested"`
	Hits           int     `json:"hits"`
	TotalBytes     int     `json:"bytes"`
	Seconds        float64 `json:"seconds"`
	OpsPerSecond   float64 `json:"ops_per_second"`
	BytesPerSecond float64 `json:"bytes_per_second"`
}

type timeSummary struct {
	Min  float64 `json:"min"`
	Max  float64 `json:"max"`
	Mean float64 `json:"mean"`
	P50  float64 `json:"p50"`
	P95  float64 `json:"p95"`
}

type scanReport struct {
	Details          []scanMetrics `json:"details"`
	FirstPassSeconds float64       `json:"first_pass_seconds"`
	FollowingSummary *timeSummary  `json:"following_summary"`
}

type randomReport struct {
	Details []randomMetrics `json:"details"`
	Summary timeSummary     `json:"summary"`
}

type report struct {
	Engine          string       `json:"engine"`
	ReadMode        string       `json:"read_mode"`
	DeserializeMode string       `json:"deserialize_mode"`
	PebblePath      string       `json:"db_path"`
	ScanPasses      int          `json:"scan_passes"`
	RandomPasses    int          `json:"random_passes"`
	RandomKeys      int          `json:"random_keys"`
	Seed            int64        `json:"seed"`
	KeysFound       int          `json:"keys_found"`
	Scan            scanReport   `json:"scan"`
	Random          randomReport `json:"random"`
}

// parseConfig recoge los parametros de la prueba desde linea de comandos.
func parseConfig() config {
	defaultPath := filepath.Join(".", "pebble")
	conf := config{}
	flag.StringVar(&conf.pebblePath, "pebble-path", defaultPath, "Ruta del directorio Pebble")
	flag.IntVar(&conf.scanPasses, "scan-passes", 3, "Numero de recorridos completos de la tabla")
	flag.IntVar(&conf.randomPasses, "random-passes", 3, "Numero de rondas aleatorias")
	flag.IntVar(&conf.randomKeys, "random-keys", 1000, "Numero de llaves aleatorias por ronda")
	flag.Int64Var(&conf.seed, "seed", 12345, "Semilla reproducible para la seleccion aleatoria")
	flag.StringVar(&conf.readMode, "read-mode", "full", "Modo de lectura: full o keys")
	flag.StringVar(&conf.deserializeMode, "deserialize-mode", "raw", "Modo de deserialización: raw o decoded")
	flag.StringVar(&conf.outputJSON, "output-json", defaultJSONPath, "Ruta del resumen JSON a generar")
	flag.StringVar(&conf.outputCSV, "output-csv", defaultCSVPath, "Ruta del detalle CSV a generar")
	flag.Parse()
	return conf
}

// validate comprueba que la configuracion es coherente antes de abrir la base.
func (c config) validate() error {
	if c.scanPasses <= 0 {
		return errors.New("scan-passes debe ser mayor que 0")
	}
	if c.randomPasses <= 0 {
		return errors.New("random-passes debe ser mayor que 0")
	}
	if c.randomKeys <= 0 {
		return errors.New("random-keys debe ser mayor que 0")
	}
	if c.readMode != "full" && c.readMode != "keys" {
		return errors.New("read-mode debe ser full o keys")
	}
	if c.deserializeMode != "raw" && c.deserializeMode != "decoded" {
		return errors.New("deserialize-mode debe ser raw o decoded")
	}
	if c.deserializeMode == "decoded" && c.readMode != "full" {
		return errors.New("deserialize-mode=decoded solo tiene sentido con read-mode=full")
	}
	return nil
}

// openDB abre Pebble en solo lectura para evitar cualquier mutacion accidental.
func openDB(path string) (*pebble.DB, error) {
	return pebble.Open(path, &pebble.Options{ReadOnly: true})
}

// safeDiv evita divisiones por cero en metricas derivadas.
func safeDiv(dividend float64, divisor float64) float64 {
	if divisor == 0 {
		return 0
	}
	return dividend / divisor
}

// percentile calcula percentiles simples por interpolacion lineal.
func percentile(values []float64, quantile float64) float64 {
	if len(values) == 0 {
		return 0
	}
	ordered := slices.Clone(values)
	slices.Sort(ordered)
	if len(ordered) == 1 {
		return ordered[0]
	}
	position := float64(len(ordered)-1) * quantile
	lower := int(position)
	upper := lower + 1
	if upper >= len(ordered) {
		upper = len(ordered) - 1
	}
	fraction := position - float64(lower)
	return ordered[lower] + (ordered[upper]-ordered[lower])*fraction
}

// summarizeTimes resume una serie con media, extremos y percentiles.
func summarizeTimes(values []float64) timeSummary {
	minimum := values[0]
	maximum := values[0]
	total := 0.0
	for _, value := range values {
		if value < minimum {
			minimum = value
		}
		if value > maximum {
			maximum = value
		}
		total += value
	}
	return timeSummary{
		Min:  minimum,
		Max:  maximum,
		Mean: total / float64(len(values)),
		P50:  percentile(values, 0.50),
		P95:  percentile(values, 0.95),
	}
}

// recordSize devuelve el tamaño imputado al registro segun el modo de lectura.
func recordSize(key []byte, value []byte, readMode string) int {
	if readMode == "keys" {
		return len(key)
	}
	return len(key) + len(value)
}

// decodeRecordValue deserializa un value Pebble con formato [ctrl][version][payload].
func decodeRecordValue(value []byte) error {
	if len(value) < 5 {
		return fmt.Errorf("record value truncado: %d bytes", len(value))
	}
	return benchbincodec.DecodePayload(value[5:])
}

// nextPrefix calcula el upper bound exclusivo de un prefijo binario.
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

// fullScan recorre la tabla HI completa, opcionalmente conservando las llaves.
func fullScan(db *pebble.DB, collectKeys bool, readMode string, deserializeMode string) (scanMetrics, error) {
	started := time.Now()
	iter, err := db.NewIter(&pebble.IterOptions{
		LowerBound: historiaPrefix,
		UpperBound: nextPrefix(historiaPrefix),
	})
	if err != nil {
		return scanMetrics{}, err
	}
	defer func() {
		_ = iter.Close()
	}()

	metrics := scanMetrics{}
	for iter.First(); iter.Valid(); iter.Next() {
		key := iter.Key()
		value := iter.Value()
		metrics.Rows++
		if readMode == "keys" {
			metrics.TotalBytes += len(key)
		} else {
			metrics.TotalBytes += recordSize(key, value, readMode)
			if deserializeMode == "decoded" {
				if err := decodeRecordValue(value); err != nil {
					return scanMetrics{}, err
				}
			}
		}
		if collectKeys {
			metrics.keys = append(metrics.keys, slices.Clone(key))
		}
	}
	if err := iter.Error(); err != nil {
		return scanMetrics{}, err
	}
	metrics.Seconds = time.Since(started).Seconds()
	metrics.RowsPerSecond = safeDiv(float64(metrics.Rows), metrics.Seconds)
	metrics.BytesPerSecond = safeDiv(float64(metrics.TotalBytes), metrics.Seconds)
	return metrics, nil
}

// keyExists localiza una llave exacta mediante SeekGE sin tocar el valor.
func keyExists(iter *pebble.Iterator, key []byte) bool {
	if !iter.SeekGE(key) {
		return false
	}
	return bytes.Equal(iter.Key(), key)
}

// randomSelection elige llaves unicas para una ronda de lecturas aleatorias.
func randomSelection(keys [][]byte, amount int, rng *rand.Rand) [][]byte {
	if amount >= len(keys) {
		return slices.Clone(keys)
	}
	permutation := rng.Perm(len(keys))
	selected := make([][]byte, 0, amount)
	for _, index := range permutation[:amount] {
		selected = append(selected, keys[index])
	}
	return selected
}

// randomReads ejecuta rondas aleatorias en modo full o solo llaves.
func randomReads(db *pebble.DB, keys [][]byte, passes int, amount int, seed int64, readMode string, deserializeMode string) ([]randomMetrics, error) {
	rng := rand.New(rand.NewSource(seed))
	results := make([]randomMetrics, 0, passes)
	keyIter, err := db.NewIter(nil)
	if err != nil {
		return nil, err
	}
	defer func() {
		_ = keyIter.Close()
	}()

	for passIndex := 1; passIndex <= passes; passIndex++ {
		selected := randomSelection(keys, amount, rng)
		started := time.Now()
		metrics := randomMetrics{Pass: passIndex, Requested: len(selected)}

		for _, key := range selected {
			if readMode == "keys" {
				if !keyExists(keyIter, key) {
					continue
				}
				metrics.Hits++
				metrics.TotalBytes += len(key)
				continue
			}
			value, closer, err := db.Get(key)
			if err != nil {
				if errors.Is(err, pebble.ErrNotFound) {
					continue
				}
				return nil, err
			}
			metrics.Hits++
			metrics.TotalBytes += len(key) + len(value)
			if deserializeMode == "decoded" {
				if err := decodeRecordValue(value); err != nil {
					_ = closer.Close()
					return nil, err
				}
			}
			if closeErr := closer.Close(); closeErr != nil {
				return nil, closeErr
			}
		}

		metrics.Seconds = time.Since(started).Seconds()
		metrics.OpsPerSecond = safeDiv(float64(metrics.Hits), metrics.Seconds)
		metrics.BytesPerSecond = safeDiv(float64(metrics.TotalBytes), metrics.Seconds)
		results = append(results, metrics)
	}

	return results, nil
}

// printScanSummary informa la primera pasada y la media del resto.
func printScanSummary(results []scanMetrics) {
	first := results[0]
	fmt.Println("Recorridos completos Pebble")
	fmt.Printf("  registros: %d\n", first.Rows)
	fmt.Printf("  llaves guardadas: %d\n", len(first.keys))
	fmt.Printf("  bytes leidos por pasada: %d\n", first.TotalBytes)
	fmt.Printf("  primera pasada: %.6f s\n", first.Seconds)
	fmt.Printf("  throughput primera pasada: %.2f reg/s, %.2f B/s\n", first.RowsPerSecond, first.BytesPerSecond)
	if len(results) <= 1 {
		return
	}
	following := make([]float64, 0, len(results)-1)
	fmt.Print("  siguientes pasadas: [")
	for index, result := range results[1:] {
		if index > 0 {
			fmt.Print(" ")
		}
		fmt.Printf("%.6f", result.Seconds)
		following = append(following, result.Seconds)
	}
	fmt.Println("]")
	summary := summarizeTimes(following)
	fmt.Printf("  media siguientes: %.6f s\n", summary.Mean)
	fmt.Printf("  min/max siguientes: %.6f / %.6f s\n", summary.Min, summary.Max)
	fmt.Printf("  p50/p95 siguientes: %.6f / %.6f s\n", summary.P50, summary.P95)
}

// printRandomSummary informa el detalle de cada ronda aleatoria y su media.
func printRandomSummary(results []randomMetrics) {
	fmt.Println("Lecturas aleatorias Pebble")
	times := make([]float64, 0, len(results))
	for _, result := range results {
		fmt.Printf(
			"  ronda %d: solicitadas=%d hits=%d bytes=%d tiempo=%.6f s ops/s=%.2f B/s=%.2f\n",
			result.Pass,
			result.Requested,
			result.Hits,
			result.TotalBytes,
			result.Seconds,
			result.OpsPerSecond,
			result.BytesPerSecond,
		)
		times = append(times, result.Seconds)
	}
	summary := summarizeTimes(times)
	fmt.Printf("  media rondas aleatorias: %.6f s\n", summary.Mean)
	fmt.Printf("  min/max rondas aleatorias: %.6f / %.6f s\n", summary.Min, summary.Max)
	fmt.Printf("  p50/p95 rondas aleatorias: %.6f / %.6f s\n", summary.P50, summary.P95)
}

// buildReport construye un resumen serializable con configuracion y metricas.
func buildReport(conf config, scanResults []scanMetrics, randomResults []randomMetrics) report {
	result := report{
		Engine:          "pebble",
		ReadMode:        conf.readMode,
		DeserializeMode: conf.deserializeMode,
		PebblePath:      conf.pebblePath,
		ScanPasses:      conf.scanPasses,
		RandomPasses:    conf.randomPasses,
		RandomKeys:      conf.randomKeys,
		Seed:            conf.seed,
		KeysFound:       len(scanResults[0].keys),
		Scan: scanReport{
			Details:          scanResults,
			FirstPassSeconds: scanResults[0].Seconds,
		},
		Random: randomReport{
			Details: randomResults,
			Summary: summarizeTimes(extractRandomTimes(randomResults)),
		},
	}
	if len(scanResults) > 1 {
		following := make([]float64, 0, len(scanResults)-1)
		for _, item := range scanResults[1:] {
			following = append(following, item.Seconds)
		}
		summary := summarizeTimes(following)
		result.Scan.FollowingSummary = &summary
	}
	return result
}

// extractRandomTimes extrae la duracion de cada ronda aleatoria.
func extractRandomTimes(results []randomMetrics) []float64 {
	times := make([]float64, 0, len(results))
	for _, result := range results {
		times = append(times, result.Seconds)
	}
	return times
}

// writeJSONReport escribe el resumen completo en JSON legible.
func writeJSONReport(result report, outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return err
	}
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(outputPath, data, 0o644)
}

// writeCSVReport vuelca el detalle plano de las pasadas secuenciales y aleatorias.
func writeCSVReport(scanResults []scanMetrics, randomResults []randomMetrics, outputPath string, conf config) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return err
	}
	file, err := os.Create(outputPath)
	if err != nil {
		return err
	}
	defer func() {
		_ = file.Close()
	}()

	writer := csv.NewWriter(file)
	defer writer.Flush()

	if err := writer.Write([]string{"read_mode", "deserialize_mode", "section", "pass", "rows", "requested", "hits", "bytes", "seconds", "rows_per_second", "ops_per_second", "bytes_per_second"}); err != nil {
		return err
	}
	for _, item := range scanResults {
		row := []string{
			conf.readMode,
			conf.deserializeMode,
			"scan",
			fmt.Sprintf("%d", item.Pass),
			fmt.Sprintf("%d", item.Rows),
			"",
			"",
			fmt.Sprintf("%d", item.TotalBytes),
			fmt.Sprintf("%.9f", item.Seconds),
			fmt.Sprintf("%.2f", item.RowsPerSecond),
			"",
			fmt.Sprintf("%.2f", item.BytesPerSecond),
		}
		if err := writer.Write(row); err != nil {
			return err
		}
	}
	for _, item := range randomResults {
		row := []string{
			conf.readMode,
			conf.deserializeMode,
			"random",
			fmt.Sprintf("%d", item.Pass),
			"",
			fmt.Sprintf("%d", item.Requested),
			fmt.Sprintf("%d", item.Hits),
			fmt.Sprintf("%d", item.TotalBytes),
			fmt.Sprintf("%.9f", item.Seconds),
			"",
			fmt.Sprintf("%.2f", item.OpsPerSecond),
			fmt.Sprintf("%.2f", item.BytesPerSecond),
		}
		if err := writer.Write(row); err != nil {
			return err
		}
	}
	return writer.Error()
}

func main() {
	conf := parseConfig()
	if err := conf.validate(); err != nil {
		panic(err)
	}

	db, err := openDB(conf.pebblePath)
	if err != nil {
		panic(err)
	}
	defer func() {
		_ = db.Close()
	}()

	scanResults := make([]scanMetrics, 0, conf.scanPasses)
	for passIndex := 0; passIndex < conf.scanPasses; passIndex++ {
		result, scanErr := fullScan(db, passIndex == 0, conf.readMode, conf.deserializeMode)
		if scanErr != nil {
			panic(scanErr)
		}
		result.Pass = passIndex + 1
		scanResults = append(scanResults, result)
	}
	fmt.Printf("Modo de lectura Pebble: %s\n", conf.readMode)
	fmt.Printf("Modo de deserialización Pebble: %s\n", conf.deserializeMode)
	printScanSummary(scanResults)

	randomResults, err := randomReads(db, scanResults[0].keys, conf.randomPasses, conf.randomKeys, conf.seed, conf.readMode, conf.deserializeMode)
	if err != nil {
		panic(err)
	}
	printRandomSummary(randomResults)

	report := buildReport(conf, scanResults, randomResults)
	if err := writeJSONReport(report, conf.outputJSON); err != nil {
		panic(err)
	}
	if err := writeCSVReport(scanResults, randomResults, conf.outputCSV, conf); err != nil {
		panic(err)
	}
	fmt.Printf("JSON generado en: %s\n", conf.outputJSON)
	fmt.Printf("CSV generado en: %s\n", conf.outputCSV)
}
