# check=skip=FromPlatformFlagConstDisallowed
# Сервер 1С:Предприятия 8.3.27 (Linux x86_64) для автономного запуска ibsrv/ibcmd.
# На Apple Silicon собирается и работает под эмуляцией: --platform linux/amd64.
# Установщик не копируется в образ: он подключается на время сборки из контекста "dist"
# (папка onec-dist/, в git не попадает). Сборка:
#   docker build --platform linux/amd64 --build-context dist=onec-dist -t recon-onec onec
FROM --platform=linux/amd64 debian:bookworm-slim

ARG ONEC_VERSION=8.3.27.2342

# Библиотеки, нужные серверу 1С, и русская локаль (без неё сервер не стартует корректно).
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates locales curl procps \
      libfontconfig1 libfreetype6 libglib2.0-0 libkrb5-3 libgssapi-krb5-2 \
 && sed -i 's/# ru_RU.UTF-8 UTF-8/ru_RU.UTF-8 UTF-8/' /etc/locale.gen \
 && locale-gen \
 && rm -rf /var/lib/apt/lists/*

ENV LANG=ru_RU.UTF-8 LC_ALL=ru_RU.UTF-8

# Тихая установка только серверной части (без клиента и графики).
RUN --mount=type=bind,from=dist,target=/dist \
    /dist/setup-full-${ONEC_VERSION}-x86_64.run \
      --mode unattended \
      --enable-components server,ru \
      --disable-components client_full,client_thin,client_thin_fib,desktop_icons,ws,server_admin,liberica_jre,config_storage_server

ENV ONEC_BIN=/opt/1cv8/x86_64/${ONEC_VERSION}
ENV PATH=${ONEC_BIN}:${PATH}

WORKDIR /onec
CMD ["sleep", "infinity"]
