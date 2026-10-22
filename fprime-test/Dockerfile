# F Prime v4.4.1 Ref deployment with CfdpManager (FileHandlingCfdp) in place of
# FileUplink/FileDownlink, listening as a TCP server for COSMOS on port 50000.
# --build-arg TLM_SEND=packetizer builds it with TlmPacketizer instead of TlmChan.
FROM ubuntu:24.04
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git cmake make g++ python3 python3-venv python3-pip ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
# Ref's WasmSequencer needs Rust >= 1.87, newer than Ubuntu's packaged cargo
RUN curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH=/root/.cargo/bin:$PATH
RUN git clone --depth 1 --branch v4.4.1 https://github.com/nasa/fprime /fprime
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir -r /fprime/requirements.txt
ENV PATH=/venv/bin:$PATH

COPY ref-cfdp.patch /tmp/ref-cfdp.patch
RUN cd /fprime && git apply /tmp/ref-cfdp.patch
# chan: Ref's default TlmChan (channelized telemetry, APID 1)
# packetizer: TlmPacketizer sends the RefPackets telemetry packets (APID 4)
ARG TLM_SEND=chan
COPY ref-packetizer.patch /tmp/ref-packetizer.patch
RUN case "$TLM_SEND" in \
      chan) ;; \
      packetizer) cd /fprime && git apply /tmp/ref-packetizer.patch ;; \
      *) echo "TLM_SEND must be chan or packetizer" >&2; exit 1 ;; \
    esac

WORKDIR /fprime/TestDeploymentsProject
RUN fprime-util generate && fprime-util build -j "$(nproc)"
# Stable locations for the binary and the dictionary COSMOS is generated from
RUN cp "$(find build-artifacts -path '*/bin/Ref' -type f)" /usr/local/bin/Ref \
    && cp "$(find build-artifacts -name RefTopologyDictionary.json)" /RefTopologyDictionary.json

COPY files/ /files/
RUN mkdir -p /files/uplink
WORKDIR /files
EXPOSE 50000
ENTRYPOINT ["/usr/local/bin/Ref", "-a", "0.0.0.0", "-p", "50000"]
