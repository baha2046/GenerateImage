#!/bin/bash
read -r -p "Enter file name: " name
mflux-upscale-seedvr2 \
  --image-path "$name" \
  --resolution 1024 \
  --softness 0.5 \
  --output "upscaled-$name"