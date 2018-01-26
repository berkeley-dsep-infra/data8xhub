FROM ubuntu:17.10


RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
            python3 \
            python3-dev \
            python3-pip \
            python3-setuptools \
            git \
            locales

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

RUN adduser --disabled-password --gecos "Default Jupyter user" jovyan

RUN pip3 install --no-cache-dir \
         notebook \
         ipykernel \
         ipywidgets \
         jupyterhub==0.8.1 \
         git+https://github.com/data-8/nbgitpuller@e7e36b5

RUN jupyter serverextension enable --py nbgitpuller --sys-prefix

# FIXME: pin versions here
RUN pip3 install --no-cache-dir \
         datascience \
         scipy \
         pandas \
         matplotlib

WORKDIR /home/jovyan
USER jovyan
