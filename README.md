# CeSpGRN 

## Description
Inferring cell specific GRN using single-cell gene expression data

* `src` stores the inference algorithms.
* `test` stores the `scripts` (testing scripts) and `results` (testing results generated by the scripts, too large to be pushed onto github, available upon requests).
  * `scripts_GGM`: testing script for the GGM data
  * `scripts_softODE`: testing script for the softODE data
  * `scripts_THP-1`: testing script for the THP-1 data
* `simulator` stores the simulation code:
  * `GGM`: simulator for GGM data
  * `soft_boolODE`: simulator for the softODE data
* `data` stores the generated data (available upon requests)


## Usage
See `demo.py`.
