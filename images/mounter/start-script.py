#!/usr/bin/env python3
import subprocess
import time
import os

with open(os.environ['MOUNT_SCRIPT']) as f:
    host_script = f.read()

assert 'FILESERVERS' in os.environ
assert 'MOUNT_PATH_TEMPLATE' in os.environ

while True:
    try:
        subprocess.check_call([ 'nsenter',
            # nseenter on alpine wants its options like this, and will print
            # a really unhelpful error message otherwise, boo
            '--target=1',
            '--mount',
            '--net',
            '--',
            'python3',
            '-c',
             host_script,
             os.environ['FILESERVERS'],
             os.environ['MOUNT_PATH_TEMPLATE']
        ])
    except subprocess.CalledProcessError:
        print("Host script failed")
    time.sleep(10)