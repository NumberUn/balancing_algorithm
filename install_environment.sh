#!/bin/bash

sudo apt update & wait
sudo apt upgrade -y & wait
sudo apt install python3-pip & wait
python3 -m pip install --upgrade pip & wait
pip3 install dydx_v3_python & wait
pip3 install python-dotenv & wait
pip3 install --no-cache-dir --user -r requirements.txt & wait
pip3 install --upgrade requests & wait