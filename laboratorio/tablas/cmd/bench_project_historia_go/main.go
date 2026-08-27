package main

/*
===============================================================================
Responsabilidad

Este comando mide en Go la proyección cruda de payloads bincodec sobre el flat
file de HI. En lugar de materializar el registro completo, recorre el payload y
reemite solo algunos campos en un buffer más pequeño.

Flujo

1. Carga una vez el fichero plano [len uint32 BE][payload].
2. Ejecuta dos perfiles fijos de proyección sin materializar Value.
3. Mide pasadas secuenciales completas y rondas aleatorias.
4. Emite JSON y CSV con bytes de entrada y bytes proyectados.

Diseño

- Usa benchbincodec.ProjectPayload para localizar spans ya serializados y
  copiarlos directamente a un buffer de salida.
- Los perfiles simulados son `select_246` y `select_246_list2`.
- La lectura del flat file se hace una vez para aislar CPU de parseo y copia.
===============================================================================
*/

import (
	"encoding/binary"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"math"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"time"

	"utilidades/laboratorio/tablas/benchbincodec"
)

type config struct {
	inputPath    string
	outputJSON   string
	outputCSV    string
	scanPasses   int
	randomPasses int
	randomKeys   intSliceFlag
	seed         int64
}

type intSliceFlag []int

type projectionEngine struct {
	name    string
	profile benchbincodec.ProjectionProfile
}

type runDetail struct {
	Pass                   int     `json:"pass"`
	Rows                   int     `json:"rows,omitempty"`
	Requested              int     `json:"requested,omitempty"`
	Hits                   int     `json:"hits,omitempty"`
	Bytes                  int     `json:"bytes"`
	ProducedBytes          int     `json:"produced_bytes"`
	Seconds                float64 `json:"seconds"`
	RowsPerSecond          float64 `json:"rows_per_second,omitempty"`
	OpsPerSecond           float64 `json:"ops_per_second,omitempty"`
	BytesPerSecond         float64 `json:"bytes_per_second"`
	ProducedBytesPerSecond float64 `json:"produced_bytes_per_second"`
}

type summary struct {
	Min  float64 `json:"min"`
	Max  float64 `json:"max"`
	Mean float64 `json:"mean"`
	P50  float64 `json:"p50"`
	P95  float64 `json:"p95"`
}

type randomReport struct {
	RandomKeys int         `json:"random_keys"`
	Details    []runDetail `json:"details"`
	Summary    summary     `json:"summary"`
}

type scanReport struct {
	Details          []runDetail `json:"details"`
	FirstPassSeconds float64     `json:"first_pass_seconds"`
	FollowingSummary *summary    `json:"following_summary"`
}

type engineReport struct {
	Engine            string         `json:"engine"`
	ProjectionProfile string         `json:"projection_profile"`
	FilePath          string         `json:"file_path"`
	Records           int            `json:"records"`
	FlatFileBytes     int            `json:"flat_file_bytes"`
	PayloadBytes      int            `json:"payload_bytes"`
	Scan              scanReport     `json:"scan"`
	Random            []randomReport `json:"random"`
}

type report struct {
	Config  reportConfig   `json:"config"`
	Engines []engineReport `json:"engines"`
}

type reportConfig struct {
	InputPath    string `json:"input_path"`
	ScanPasses   int    `json:"scan_passes"`
	RandomPasses int    `json:"random_passes"`
	RandomKeys   []int  `json:"random_keys"`
	Seed         int64  `json:"seed"`
}

func (f *intSliceFlag) String() string {
	return fmt.Sprint([]int(*f))
}

func (f *intSliceFlag) Set(value string) error {
	var parsed int
	_, err := fmt.Sscanf(value, "%d", &parsed)
	if err != nil {
		return fmt.Errorf("valor entero inválido %q", value)
	}
	*f = append(*f, parsed)
	return nil
}

func parseConfig() config {
	conf := config{}
	flag.StringVar(&conf.inputPath, "input-path", "historia_pebble_payloads.flatbin", "Ruta del fichero plano bincodec")
	flag.StringVar(&conf.outputJSON, "output-json", "bench_project_historia_go.json", "Ruta del informe JSON")
	flag.StringVar(&conf.outputCSV, "output-csv", "bench_project_historia_go.csv", "Ruta del informe CSV")
	flag.IntVar(&conf.scanPasses, "scan-passes", 3, "Número de pasadas secuenciales completas")
	flag.IntVar(&conf.randomPasses, "random-passes", 5, "Número de rondas aleatorias por tamaño")
	flag.Var(&conf.randomKeys, "random-keys", "Tamaño de muestra aleatoria; repetir el flag para varios valores")
	flag.Int64Var(&conf.seed, "seed", 12345, "Semilla reproducible para rondas aleatorias")
	flag.Parse()
	if len(conf.randomKeys) == 0 {
		conf.randomKeys = intSliceFlag{1000, 10000, 50000}
	}
	return conf
}

func (c config) validate() error {
	if c.scanPasses <= 0 {
		return fmt.Errorf("scan-passes debe ser mayor que 0")
	}
	if c.randomPasses <= 0 {
		return fmt.Errorf("random-passes debe ser mayor que 0")
	}
	if len(c.randomKeys) == 0 {
		return fmt.Errorf("random-keys no puede estar vacío")
	}
	for _, amount := range c.randomKeys {
		if amount <= 0 {
			return fmt.Errorf("todos los random-keys deben ser mayores que 0")
		}
	}
	return nil
}

func loadFlatRecords(path string) ([][]byte, int, int, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, 0, 0, err
	}
	records := make([][]byte, 0, 1024)
	offset := 0
	payloadBytes := 0
	for offset < len(data) {
		if offset+4 > len(data) {
			return nil, 0, 0, fmt.Errorf("flatbin truncado leyendo longitud en offset %d", offset)
		}
		length := int(binary.BigEndian.Uint32(data[offset : offset+4]))
		offset += 4
		end := offset + length
		if end > len(data) {
			return nil, 0, 0, fmt.Errorf("flatbin truncado leyendo payload en offset %d", offset)
		}
		records = append(records, data[offset:end])
		payloadBytes += length
		offset = end
	}
	return records, len(data), payloadBytes, nil
}

func safeDiv(dividend float64, divisor float64) float64 {
	if divisor == 0 {
		return 0
	}
	return dividend / divisor
}

func summarize(values []float64) *summary {
	if len(values) == 0 {
		return nil
	}
	ordered := append([]float64(nil), values...)
	sort.Float64s(ordered)
	return &summary{
		Min:  ordered[0],
		Max:  ordered[len(ordered)-1],
		Mean: mean(ordered),
		P50:  percentileSorted(ordered, 0.50),
		P95:  percentileSorted(ordered, 0.95),
	}
}

func mean(values []float64) float64 {
	total := 0.0
	for _, value := range values {
		total += value
	}
	return total / float64(len(values))
}

func percentileSorted(sortedValues []float64, pct float64) float64 {
	if len(sortedValues) == 1 {
		return sortedValues[0]
	}
	position := float64(len(sortedValues)-1) * pct
	lower := int(math.Floor(position))
	upper := int(math.Ceil(position))
	if lower == upper {
		return sortedValues[lower]
	}
	fraction := position - float64(lower)
	return sortedValues[lower] + (sortedValues[upper]-sortedValues[lower])*fraction
}

func availableEngines() []projectionEngine {
	return []projectionEngine{
		{name: "bincodec-go-project-select_246", profile: benchbincodec.ProjectionSelect246},
		{name: "bincodec-go-project-select_246_list2", profile: benchbincodec.ProjectionSelect246List2},
	}
}

func runFullScan(records [][]byte, profile benchbincodec.ProjectionProfile) (float64, int, int, int, error) {
	started := time.Now()
	totalBytes := 0
	producedBytes := 0
	scratch := make([]byte, 0, 256)
	for _, payload := range records {
		projected, err := benchbincodec.ProjectPayload(payload, profile, scratch[:0])
		if err != nil {
			return 0, 0, 0, 0, err
		}
		scratch = projected
		totalBytes += len(payload)
		producedBytes += len(projected)
	}
	return time.Since(started).Seconds(), len(records), totalBytes, producedBytes, nil
}

func pickRandomRecords(records [][]byte, amount int, rng *rand.Rand) [][]byte {
	sampleSize := amount
	if sampleSize > len(records) {
		sampleSize = len(records)
	}
	indexes := rng.Perm(len(records))[:sampleSize]
	selected := make([][]byte, sampleSize)
	for i, index := range indexes {
		selected[i] = records[index]
	}
	return selected
}

func runRandomReads(records [][]byte, profile benchbincodec.ProjectionProfile, randomKeys int, passes int, seed int64) ([]runDetail, error) {
	rng := rand.New(rand.NewSource(seed))
	results := make([]runDetail, 0, passes)
	scratch := make([]byte, 0, 256)
	for passIndex := 1; passIndex <= passes; passIndex++ {
		selected := pickRandomRecords(records, randomKeys, rng)
		started := time.Now()
		totalBytes := 0
		producedBytes := 0
		for _, payload := range selected {
			projected, err := benchbincodec.ProjectPayload(payload, profile, scratch[:0])
			if err != nil {
				return nil, err
			}
			scratch = projected
			totalBytes += len(payload)
			producedBytes += len(projected)
		}
		elapsed := time.Since(started).Seconds()
		results = append(results, runDetail{
			Pass:                   passIndex,
			Requested:              len(selected),
			Hits:                   len(selected),
			Bytes:                  totalBytes,
			ProducedBytes:          producedBytes,
			Seconds:                elapsed,
			OpsPerSecond:           safeDiv(float64(len(selected)), elapsed),
			BytesPerSecond:         safeDiv(float64(totalBytes), elapsed),
			ProducedBytesPerSecond: safeDiv(float64(producedBytes), elapsed),
		})
	}
	return results, nil
}

func buildEngineReport(conf config, records [][]byte, flatBytes int, payloadBytes int, engine projectionEngine) (engineReport, error) {
	scanTimes := make([]float64, 0, conf.scanPasses)
	scanDetails := make([]runDetail, 0, conf.scanPasses)
	rows := 0
	decodedBytes := 0
	producedBytes := 0
	for passIndex := 1; passIndex <= conf.scanPasses; passIndex++ {
		elapsed, currentRows, currentBytes, currentProduced, err := runFullScan(records, engine.profile)
		if err != nil {
			return engineReport{}, err
		}
		rows = currentRows
		decodedBytes = currentBytes
		producedBytes = currentProduced
		scanTimes = append(scanTimes, elapsed)
		scanDetails = append(scanDetails, runDetail{
			Pass:                   passIndex,
			Rows:                   rows,
			Bytes:                  decodedBytes,
			ProducedBytes:          producedBytes,
			Seconds:                elapsed,
			RowsPerSecond:          safeDiv(float64(rows), elapsed),
			BytesPerSecond:         safeDiv(float64(decodedBytes), elapsed),
			ProducedBytesPerSecond: safeDiv(float64(producedBytes), elapsed),
		})
	}

	randomReports := make([]randomReport, 0, len(conf.randomKeys))
	for _, amount := range conf.randomKeys {
		details, err := runRandomReads(records, engine.profile, amount, conf.randomPasses, conf.seed+int64(amount))
		if err != nil {
			return engineReport{}, err
		}
		randomTimes := make([]float64, 0, len(details))
		for _, detail := range details {
			randomTimes = append(randomTimes, detail.Seconds)
		}
		randomReports = append(randomReports, randomReport{
			RandomKeys: amount,
			Details:    details,
			Summary:    *summarize(randomTimes),
		})
	}

	var following *summary
	if len(scanTimes) > 1 {
		following = summarize(scanTimes[1:])
	}

	return engineReport{
		Engine:            engine.name,
		ProjectionProfile: string(engine.profile),
		FilePath:          conf.inputPath,
		Records:           len(records),
		FlatFileBytes:     flatBytes,
		PayloadBytes:      payloadBytes,
		Scan: scanReport{
			Details:          scanDetails,
			FirstPassSeconds: scanTimes[0],
			FollowingSummary: following,
		},
		Random: randomReports,
	}, nil
}

func writeJSONReport(reportData report, outputPath string) error {
	if err := os.MkdirAll(filepath.Dir(outputPath), 0o755); err != nil && filepath.Dir(outputPath) != "." {
		return err
	}
	data, err := json.MarshalIndent(reportData, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(outputPath, data, 0o644)
}

func writeCSVReport(engines []engineReport, outputPath string) error {
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
	if err := writer.Write([]string{"engine", "projection_profile", "random_keys", "scan_first_seconds", "scan_following_mean_seconds", "random_mean_seconds", "scan_first_rows_per_second", "scan_first_bytes_per_second", "scan_first_produced_bytes_per_second", "random_ops_per_second", "random_bytes_per_second", "random_produced_bytes_per_second"}); err != nil {
		return err
	}

	for _, engine := range engines {
		scanFirst := engine.Scan.Details[0]
		followingMean := ""
		if engine.Scan.FollowingSummary != nil {
			followingMean = fmt.Sprintf("%.12f", engine.Scan.FollowingSummary.Mean)
		}
		for _, randomReport := range engine.Random {
			firstRandom := randomReport.Details[0]
			row := []string{
				engine.Engine,
				engine.ProjectionProfile,
				fmt.Sprintf("%d", randomReport.RandomKeys),
				fmt.Sprintf("%.12f", engine.Scan.FirstPassSeconds),
				followingMean,
				fmt.Sprintf("%.12f", randomReport.Summary.Mean),
				fmt.Sprintf("%.6f", scanFirst.RowsPerSecond),
				fmt.Sprintf("%.6f", scanFirst.BytesPerSecond),
				fmt.Sprintf("%.6f", scanFirst.ProducedBytesPerSecond),
				fmt.Sprintf("%.6f", firstRandom.OpsPerSecond),
				fmt.Sprintf("%.6f", firstRandom.BytesPerSecond),
				fmt.Sprintf("%.6f", firstRandom.ProducedBytesPerSecond),
			}
			if err := writer.Write(row); err != nil {
				return err
			}
		}
	}
	return writer.Error()
}

func printSummary(engines []engineReport) {
	fmt.Println("Resumen proyección Go sobre flat file bincodec")
	for _, engine := range engines {
		first := engine.Scan.Details[0]
		fmt.Printf("  %s scan_first=%.6fs produced_bytes=%d\n", engine.Engine, engine.Scan.FirstPassSeconds, first.ProducedBytes)
		for _, randomReport := range engine.Random {
			fmt.Printf("  random_keys=%d random_mean=%.6fs\n", randomReport.RandomKeys, randomReport.Summary.Mean)
		}
	}
}

func main() {
	conf := parseConfig()
	if err := conf.validate(); err != nil {
		panic(err)
	}
	records, flatBytes, payloadBytes, err := loadFlatRecords(conf.inputPath)
	if err != nil {
		panic(err)
	}
	engines := make([]engineReport, 0, len(availableEngines()))
	for _, engine := range availableEngines() {
		engineReport, buildErr := buildEngineReport(conf, records, flatBytes, payloadBytes, engine)
		if buildErr != nil {
			panic(buildErr)
		}
		engines = append(engines, engineReport)
	}
	reportData := report{
		Config: reportConfig{
			InputPath:    conf.inputPath,
			ScanPasses:   conf.scanPasses,
			RandomPasses: conf.randomPasses,
			RandomKeys:   []int(conf.randomKeys),
			Seed:         conf.seed,
		},
		Engines: engines,
	}
	if err := writeJSONReport(reportData, conf.outputJSON); err != nil {
		panic(err)
	}
	if err := writeCSVReport(engines, conf.outputCSV); err != nil {
		panic(err)
	}
	printSummary(engines)
	fmt.Printf("JSON generado en: %s\n", conf.outputJSON)
	fmt.Printf("CSV generado en: %s\n", conf.outputCSV)
}
