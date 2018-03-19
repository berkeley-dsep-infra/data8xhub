#!/bin/bash
set -euxo pipefail

# Very simple script to build and push images
# Should be replaced by chartpress or similar at some point
# Uses google container image builder for simplicity
IMAGE="${1}"
TAG=$(git log -n1 --pretty="%h" ${IMAGE})
IMAGE_SPEC="gcr.io/data8x-scratch/${IMAGE}:${TAG}"
gcloud container builds submit --tag ${IMAGE_SPEC} ${IMAGE}

echo "Built and pushed ${IMAGE_SPEC}"
