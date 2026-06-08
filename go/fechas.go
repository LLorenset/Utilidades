package main

import (
	"fmt"
	"math"
	"time"
)

func main() {
	// base := time.Date(1975, 12, 8, 0, 0, 0, 0, time.UTC)
	// num := uint64(time.Since(base) / (24 * time.Hour))
	// fmt.Println(num)
	// num = num % 18_446
	// fmt.Println(num)
	// num = num * 1e15
	// fmt.Println(num)

	base := time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)
	num := (uint64(time.Since(base)/(24*time.Hour)) % 18_446) * 1e15
	fmt.Println(num)

	fmt.Println("base unix ", base.Unix())

	max := uint64(18_446_744_073_709_551_615)
	fmt.Println(max)

	var max1 uint64 = math.MaxUint64
	max1 = max1 + 1
	fmt.Println(max1 + 1)

}
