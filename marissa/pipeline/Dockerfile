# AHA 2026 pipeline — reproducible build image.
# Includes Icarus Verilog, Yosys, and OpenSTA so `run_pipeline.py` runs
# end-to-end without host EDA setup.
#
# Build:  docker build -t aha-pipeline .
# Run:    docker run --rm -it \
#           -e ANTHROPIC_API_KEY -e OPENAI_API_KEY -e GOOGLE_API_KEY \
#           -v "$PWD":/work aha-pipeline \
#           python run_pipeline.py --target ethmac --num-trojans 3

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        iverilog yosys \
        git build-essential cmake \
        libtcl8.6 tcl-dev tk-dev \
        swig \
        libeigen3-dev \
        flex bison \
        libreadline-dev \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Build OpenSTA from source (no upstream apt package).
RUN git clone --depth 1 https://github.com/The-OpenROAD-Project/OpenSTA.git /tmp/opensta \
 && cd /tmp/opensta && cmake -B build -S . && cmake --build build -j$(nproc) \
 && install -m 0755 build/sta /usr/local/bin/sta \
 && rm -rf /tmp/opensta

WORKDIR /work
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

CMD ["python3", "run_pipeline.py", "--help"]
