ARG BUILD_ARCH=amd64
FROM ${BUILD_ARCH}/ubuntu:bionic

ARG BUILD_ARCH=amd64
ARG DEBIAN_ARCH=${BUILD_ARCH}
ARG CPU_ARCH=x86_64

COPY docker/multiarch_build/bin/qemu-* /usr/bin/

RUN apt-get update && \
    apt-get install --no-install-recommends --yes \
        sox jq alsa-utils espeak-ng sphinxtrain perl \
        python3 python3-pip \
        libatlas-base-dev libatlas3-base \
        bc

COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/bin/voice2json /usr/bin/
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/bin /usr/lib/voice2json/bin
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/etc /usr/lib/voice2json/etc
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/marytts /usr/lib/voice2json/marytts
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/build_${CPU_ARCH} /usr/lib/voice2json/build_${CPU_ARCH}
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/voice2json /usr/lib/voice2json/voice2json
COPY debian/voice2json_1.0_${DEBIAN_ARCH}/usr/lib/voice2json/site /usr/lib/voice2json/site

ENTRYPOINT ["voice2json"]