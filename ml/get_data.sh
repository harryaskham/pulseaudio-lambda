#!/usr/bin/env sh

wget https://zenodo.org/records/3338373/files/musdb18hq.zip
mkdir -p data/musdb18hq
unzip musdb18hq.zip -d data/musdb18hq
