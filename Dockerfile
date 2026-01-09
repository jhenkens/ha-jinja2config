ARG BUILD_FROM
FROM $BUILD_FROM

COPY requirements.txt /tmp/

RUN \
  pip3 install -r /tmp/requirements.txt && \
  apk add --no-cache inotify-tools gettext nodejs npm && \
  npm install -g prettier && \
  rm /tmp/requirements.txt

COPY rootfs /