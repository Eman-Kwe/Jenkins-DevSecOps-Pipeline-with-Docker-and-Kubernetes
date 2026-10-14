# Start from the official Jenkins LTS image with JDK 17.
# LTS = Long Term Support — stable release, not the bleeding-edge weekly build.
FROM jenkins/jenkins:2.504.3-lts-jdk17

# Switch to root so we can install system packages.
# Jenkins switches back to the jenkins user at the bottom.
USER root

# Install system dependencies:
#   docker.io     — Docker CLI so pipeline stages can run docker build/push.
#                   It talks to Docker Desktop through the socket we mount at runtime.
#   python3       — needed to run scripts/security_summary.py
#   python3-venv  — needed to create the isolated scanner virtual environment
#   curl          — used below to download Trivy, kind, kubectl
#   ca-certificates — so curl can verify HTTPS certificates
# --no-install-recommends keeps the image smaller by skipping optional packages.
# Cleaning apt cache at the end removes the package index from the final image layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      docker.io \
      python3 \
      python3-venv \
      curl \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Install Trivy 0.75.0 — the latest stable release.
# We hardcode the version directly in the URL rather than using ARG variables
# because ARG expansion inside quoted URL strings is unreliable in some
# Docker BuildKit versions and was causing 404 errors.
#
# What a .tar.gz is: a compressed archive (like a zip file).
#   tar -xzf  = extract (-x) a gzip-compressed (-z) file (-f)
#   -C /usr/local/bin trivy  = extract only the 'trivy' binary into /usr/local/bin
# After extraction we delete the archive to keep the image layer small.
#
# Trivy is used in 4 pipeline stages:
#   secrets scan, config scan, image scan, and SBOM generation
RUN curl -sSfL \
      "https://github.com/aquasecurity/trivy/releases/download/v0.75.0/trivy_0.75.0_Linux-64bit.tar.gz" \
      -o /tmp/trivy.tar.gz \
 && tar -xzf /tmp/trivy.tar.gz -C /usr/local/bin trivy \
 && rm /tmp/trivy.tar.gz \
 && chmod +x /usr/local/bin/trivy

# Install kind v0.24.0 and kubectl v1.31.1 — both are single static binaries.
# A static binary means it has no dependencies; just download and run.
#
#   kind    — Kubernetes in Docker; the pipeline uses this to load the app image
#             into the cluster before deploying
#   kubectl — Kubernetes CLI; the pipeline uses this to apply manifests,
#             wait for rollouts, and run smoke test pods
RUN curl -sSfLo /usr/local/bin/kind \
      "https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-amd64" \
 && curl -sSfLo /usr/local/bin/kubectl \
      "https://dl.k8s.io/release/v1.31.1/bin/linux/amd64/kubectl" \
 && chmod +x /usr/local/bin/kind /usr/local/bin/kubectl

# Install Python-based scanners inside an isolated virtual environment.
# A venv is a self-contained Python environment — packages installed here
# never conflict with system Python packages.
#
#   semgrep   — SAST: reads Python source code and flags dangerous patterns
#               using the p/python ruleset; pipeline fails on ERROR-level findings
#   pip-audit — SCA: checks requirements.txt against known CVE databases;
#               pipeline fails on any known vulnerability
RUN python3 -m venv /opt/scanners \
 && /opt/scanners/bin/pip install --no-cache-dir \
      semgrep==1.90.0 \
      pip-audit==2.7.3

# Add the venv's bin directory to PATH so pipeline stages can call
# semgrep and pip-audit directly without the full /opt/scanners/bin/ prefix.
ENV PATH="/opt/scanners/bin:${PATH}"

# Drop back to the jenkins user.
# All pipeline builds run as jenkins, not root.
# Root was only needed for apt-get and the binary installs above.
USER jenkins
