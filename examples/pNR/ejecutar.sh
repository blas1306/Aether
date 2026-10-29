#!/bin/bash

echo "Prueba usando compiler-next"
time aether run examples/pNR/probandoNR1.ae

echo "Prueba usando compiler-rs"
time aether-legacy --backend=ast examples/pNR/probandoNR2.ae
