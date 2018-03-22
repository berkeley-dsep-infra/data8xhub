FROM python:3.6-slim-stretch

RUN pip3 install --no-cache-dir tornado ruamel.yaml oauthlib psycopg2

RUN mkdir -p /srv/hubsharder
ADD sharder.py /srv/hubsharder/sharder.py
ADD ltivalidator.py /srv/hubsharder/ltivalidator.py
ADD request-sharder.py /srv/hubsharder/request-sharder.py

WORKDIR /srv/hubsharder