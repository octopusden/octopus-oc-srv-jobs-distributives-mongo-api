ARG DOCKER_REGISTRY_HOST=ghcr.io
ARG TAG=latest
ARG PYTHON_VERSION=3.7
FROM ${DOCKER_REGISTRY_HOST}/octopusden/octopus-oc-srv-jobs-vm-mongodb:${TAG} as mongotest

USER root

RUN rm -rf /etc/apt/sources.list.d/*mongo* && \
    apt-get update && \
    apt-get install --assume-yes python3-pip && \
    apt-get clean && \
    rm -rf /var/cache/apt/*

RUN rm -rf /build
COPY --chown=root:root . /build
WORKDIR /build

RUN python3 -m pip install $(pwd)

ENV MONGO_INITDB_ROOT_USERNAME=test
ENV MONGO_INITDB_ROOT_PASSWORD=test
ENV MONGO_INITDB_DATABASE=mongoenginetest

RUN chmod 755 ./mongo_tests_in_docker.sh && ./mongo_tests_in_docker.sh 

FROM python:${PYTHON_VERSION}

COPY . /build

WORKDIR /build
RUN rm -rf mongo_tests*.sh && python -m pip install $(pwd)

HEALTHCHECK --interval=1m --timeout=30s --start-period=15s --retries=3 \
CMD curl -v --silent --data '{"count": 10}' --request GET --header 'content-type: application/json' \
    'http://localhost:5700/get_distributives' 2>&1 | grep '< HTTP/1.1 200 OK'

ENTRYPOINT ["python3", "-m", "gunicorn", "oc_distributives_mongo_api.wsgi:app", "--timeout", "0", "-b", "0.0.0.0:5700" ]

