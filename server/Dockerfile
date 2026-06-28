FROM python:3.12-alpine

# the two options below are placeholders overwritten by docker-compose
ARG GIT_REMOTE=phoebe-project
ARG PHOEBE_BRANCH=2.4.22

# build deps for PHOEBE's C extensions
RUN apk add --no-cache git build-base musl-dev

# clone + install the requested PHOEBE version
RUN git clone --branch ${PHOEBE_BRANCH} --single-branch --depth 1 \
      https://github.com/${GIT_REMOTE}/phoebe2.git /phoebe
WORKDIR /phoebe
RUN pip install --upgrade pip && pip install --no-cache-dir .

# server runtime deps
RUN pip install --no-cache-dir flask flask-cors gunicorn

WORKDIR /tables
COPY server.py /tables/server.py

EXPOSE 80

# server.py exposes `app`; worker/timeout tuning comes from GUNICORN_CMD_ARGS
# (set per-service in compose). --bind lives here so the container listens on 80.
ENTRYPOINT ["gunicorn"]
CMD ["server:app", "--bind", "0.0.0.0:80"]
