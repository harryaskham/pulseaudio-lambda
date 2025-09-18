#!/usr/bin/env sh

cd data
wget https://zenodo.org/records/3338373/files/musdb18hq.zip
mkdir -p musdb
unzip musdb18hq.zip -d data/musdb
