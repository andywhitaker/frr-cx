# Nokia EDA CX SimNode image for FRR
#
#   docker build -t ghcr.io/andywhitaker/frr-cx:10.6.1 .
#   docker pull  ghcr.io/andywhitaker/frr-cx:10.6.1
#
# Base: official FRRouting release image

FROM quay.io/frrouting/frr:10.6.1

ARG FRR_VERSION=10.6.1
ARG IMAGE_SOURCE=https://github.com/andywhitaker/frr-cx

LABEL org.opencontainers.image.title="frr-cx" \
      org.opencontainers.image.description="FRR SimNode for Nokia EDA CX — configs from eda-asvr" \
      org.opencontainers.image.version="${FRR_VERSION}" \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.url="${IMAGE_SOURCE}" \
      org.opencontainers.image.base.name="quay.io/frrouting/frr:10.6.1" \
      org.opencontainers.image.licenses="GPL-2.0-or-later"

# Bootstrap: discover CX identity, pull configs from artifact server, start FRR
COPY get_configs.py /opt/frr-cx/get_configs.py
COPY wrapper.sh /usr/local/bin/wrapper.sh

RUN chmod 0755 /usr/local/bin/wrapper.sh /opt/frr-cx/get_configs.py

# CX launches the container command as configured on the SimNode / topology image.
CMD ["/usr/local/bin/wrapper.sh"]
