#!/bin/bash
set -euo pipefail

# Very simple script to build and push images
# Should be replaced by chartpress or similar at some point
# Uses google container image builder for simplicity
IMAGE="${1}"
TAG=$(git log -n1 --pretty="%h" ${IMAGE})
IMAGE_SPEC="gcr.io/data8x-scratch/${IMAGE}:${TAG}"

if [ -e "${IMAGE}/pre-build-hook.bash" ]; then
    echo "Executing ${IMAGE}/pre-build-hook.bash"
    $(cd ${IMAGE} && bash pre-build-hook.bash)
fi

gcloud container builds submit --tag ${IMAGE_SPEC} ${IMAGE}


echo "Built and pushed ${IMAGE_SPEC}"
