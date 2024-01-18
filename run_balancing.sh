#!/bin/bash

python3 balancing.py config.ini &
python3 consumer.py config.ini &
python3 producer.py config.ini &
