FROM ubuntu:18.04


RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
            python3 \
            python3-dev \
            python3-pip \
            python3-setuptools \
            git \
            locales \
            build-essential

RUN echo "en_US.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen

ENV LC_ALL en_US.UTF-8
ENV LANG en_US.UTF-8
ENV LANGUAGE en_US.UTF-8

RUN adduser --disabled-password --gecos "Default Jupyter user" jovyan

# We want users to not install anything new, so no virtualenv.
# pin to notebook 5.4.1 for now, 5.5 doesn't seem to work with nbgitpuller
RUN pip3 install --no-cache-dir \
         notebook==5.4.1 \
         ipykernel==4.8.2 \
         ipywidgets==7.2.1 \
         jupyterhub==0.8.1 \
         jupyterlab==0.32.1 \
         nteract_on_jupyter==1.7.0 \
         git+https://github.com/yuvipanda/nbresuse@2aadf39 \
         git+https://github.com/data-8/nbgitpuller@e7e36b5 \
         git+https://github.com/yuvipanda/nbclearafter@53aebc8

# As a security precaution, I do not want compilers here.
# The compiler is in here just for psutil, dependency of nbresuse.
RUN apt-get purge --yes build-essential && \
    apt-get --yes autoremove

RUN jupyter serverextension enable --py nbgitpuller --sys-prefix && \
    jupyter nbextension enable --py widgetsnbextension --sys-prefix && \
    jupyter serverextension enable --py nbresuse --sys-prefix && \
    jupyter nbextension install --py nbresuse --sys-prefix && \
    jupyter nbextension enable --py nbresuse --sys-prefix && \
    jupyter nbextension install --py nbclearafter --sys-prefix && \
    jupyter nbextension enable --py nbclearafter --sys-prefix && \
    jupyter serverextension enable --py jupyterlab --sys-prefix && \
    jupyter serverextension enable --py nteract_on_jupyter --sys-prefix

# FIXME: pin versions here
RUN pip3 install --no-cache-dir \
         datascience==0.10.4 \
         scipy==1.0.1 \
         pandas==0.22.0 \
         matplotlib==2.2.2 \
         gofer_grader==1.0.3

WORKDIR /home/jovyan
USER jovyan

# Reset entrypoint, so we don't run under a shell that might swallow signals
ENTRYPOINT []
