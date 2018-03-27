#!/bin/bash

# Run by build.sh before docker image is built
# Primarily here to make sure we do not have to duplicate sharder.py
cp ../hubsharder/ltivalidator.py .
