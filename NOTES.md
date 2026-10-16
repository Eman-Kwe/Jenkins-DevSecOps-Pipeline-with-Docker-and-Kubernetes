# Engineering Notes

Deep engineering notes for the Jenkins DevSecOps pipeline: setup, troubleshooting, commands, reasoning, and study material. The project story, architecture, and results are in [README.md](README.md).

Error entries use the format: **What I saw → What caused it → How I fixed it**

## Contents

1. [Environment and versions](#1-environment-and-versions)
2. [Detailed Jenkins setup and manual rebuild](#2-detailed-jenkins-setup-and-manual-rebuild)
3. [Pipeline stage reference](#3-pipeline-stage-reference)
4. [Application notes](#4-application-notes)
5. [Dockerfile line by line](#5-dockerfile-line-by-line)
6. [Kubernetes manifests](#6-kubernetes-manifests)
7. [Environment setup errors](#7-environment-setup-errors)
8. [Jenkins image build errors](#8-jenkins-image-build-errors)
9. [Failure 1 — Flask CVE (Build #4)](#9-failure-1--flask-cve-build-4)
10. [Failure 2 — Kind image loading deep dive](#10-failure-2--kind-image-loading-deep-dive)
11. [Failure 3 — Smoke test deep dive](#11-failure-3--smoke-test-deep-dive)
12. [security_summary.py troubleshooting](#12-security_summarypy-troubleshooting)
13. [Troubleshooting playbook](#13-troubleshooting-playbook)
14. [Design decisions and production tradeoffs](#14-design-decisions-and-production-tradeoffs)
15. [Build #8 final result](#15-build-8-final-result)
16. [Interview study notes](#16-interview-study-notes)
17. [Lessons learned](#17-lessons-learned)
18. [Planned / future work](#18-planned--future-work)
19. [Screenshots checklist](#19-screenshots-checklist)
20. [Material moved from the README](#20-material-moved-from-the-readme)

---

## 1. Environment and versions

| Requirement | Version used |
|-------------|-------------|
| WSL2 with Ubuntu | 24.04 |
| Docker Desktop | 29.7.2 |
| kind | v0.27.0 |
| kubectl | v1.33.12 |
| Python 3 | 3.12.3 |
| Jenkins base image | `jenkins/jenkins:2.504.3-lts-jdk17` |
| Trivy (Jenkins image) | v0.75.0 |
| containerd in Kind node | v2.0.2 (`ctr version`) |
| Semgrep ruleset | `p/python` (151 rules in Build #8) |
| Smoke test image | `curlimages/curl:8.5.0` |
| App base image | `python:3.12-slim-bookworm` |

### Why Docker and Kubernetes are both used

Docker builds the image from the Dockerfile and tags it (`devsecops-app:8`). Kubernetes runs it: it keeps 2 replicas, restarts crashed pods, routes traffic through a Service, and replaces pods during rollouts. Kubernetes does not use Docker to run containers — it uses containerd, so the image must exist in containerd's `k8s.io` namespace.

```
Dockerfile        →  docker build     →  devsecops-app:8  (the image)
         │  docker save | ctr import
         ▼
containerd (inside Kind node)          (image stored in k8s.io namespace)
         │  kubectl apply
         ▼
Kubernetes Deployment                  (2 pods running the image)
         │
         ▼
ClusterIP Service → port 80 → pods on port 8080
```

---

## 2. Detailed Jenkins setup and manual rebuild

### Step 1 — Clone the repository

```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/Eman-Kwe/Jenkins-DevSecOps-Pipeline-with-Docker-and-Kubernetes.git
cd Jenkins-DevSecOps-Pipeline-with-Docker-and-Kubernetes
```

`git clone` downloads the repository; `cd` enters it. **Verify:** `ls` shows `Jenkinsfile`, `app/`, `jenkins/`, `k8s/`, `scripts/`.

### Step 2 — Build the Jenkins image

```bash
docker build -t jenkins-devsecops:1.0 jenkins/
```

Reads `jenkins/Dockerfile` and tags the result `jenkins-devsecops:1.0`. **Verify:** `docker images | grep jenkins-devsecops`. **Common failure:** network error downloading Trivy from GitHub.

### Step 3 — Create the kind cluster

```bash
kind create cluster --name devsecops
```

Creates a Docker container that is a Kubernetes node with a control plane. **Expected:** `Set kubectl context to "kind-devsecops"`. **Verify:** `kubectl get nodes` shows `devsecops-control-plane Ready`. **Common failure:** another kind cluster in the way — `kind delete cluster --name <name>`.

### Step 4 — Apply namespaces

```bash
kubectl apply -f k8s/namespaces.yaml
```

**Expected:** `namespace/dev created`, `namespace/prod created`. **Verify:** `kubectl get ns dev prod`.

### Step 5 — Create the Jenkins volume and start the container

```bash
docker volume create jenkins_home

docker run -d --name jenkins --restart unless-stopped \
  -u root \
  -p 8080:8080 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --network kind \
  jenkins-devsecops:1.0
```

| Flag | Meaning |
|------|---------|
| `-d` | Run in background |
| `--name jenkins` | Container name |
| `--restart unless-stopped` | Restart if Docker restarts |
| `-u root` | Needed for Docker socket access (lab only) |
| `-p 8080:8080` | Expose Jenkins UI |
| `-v jenkins_home:/var/jenkins_home` | Persist Jenkins data |
| `-v /var/run/docker.sock:...` | Give Jenkins access to the Docker daemon |
| `--network kind` | Same network as the Kind cluster |

**Verify:** `docker ps --filter name=jenkins` shows `Up`.

### Step 6 — Complete Jenkins setup

```bash
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

Open `http://localhost:8080`, paste the password, choose **Install suggested plugins**, create an admin user. **Verify:** dashboard loads with no red error banners.

### Step 7 — Add the kubeconfig credential

```bash
kind get kubeconfig --name devsecops --internal > kind-internal.kubeconfig

docker cp kind-internal.kubeconfig jenkins:/tmp/k
docker exec jenkins kubectl --kubeconfig /tmp/k get nodes
docker exec jenkins rm /tmp/k
```

In Jenkins: **Manage Jenkins → Credentials → System → Global credentials → Add Credentials** — Kind: Secret file, File: `kind-internal.kubeconfig`, ID: `kind-kubeconfig`.

```bash
rm kind-internal.kubeconfig
```

**Why `--internal`:** the default kubeconfig points at `127.0.0.1`, which inside the Jenkins container is Jenkins itself. `--internal` uses the cluster's address on the Docker network.

### Step 8 — Create the pipeline job

**New Item → `devsecops-pipeline` → Pipeline → OK**, then: Definition **Pipeline script from SCM**, SCM **Git**, Repository URL your GitHub repo URL ending in `.git`, Branch the active project branch, Script Path `Jenkinsfile`. Save.

### Step 9 — Run the pipeline

Click **Build Now**. The first run downloads scanner databases and takes longer. When it reaches **Approve prod**, approve it in Stage View.

**Verify:**

```bash
kubectl -n prod get pods,svc
kubectl -n prod port-forward svc/devsecops-app 9090:80 &
sleep 1
curl -s localhost:9090/version
kill %1
kubectl -n prod exec deploy/devsecops-app -- id
kubectl -n prod exec deploy/devsecops-app -- touch /app/test
```

Expected: 2 pods Running, version returns the build number, UID 10001, `touch` fails with `Read-only file system`.

---

## 3. Pipeline stage reference

**Checkout.** Jenkins clones from GitHub. Local uncommitted changes do not affect a build.

**Secrets scan.** `trivy fs . --scanners secret --exit-code 1`. Runs first: if credentials are committed, nothing else should proceed. The Jenkinsfile runs it twice: once with `--exit-code 0` to write `trivy-secrets.json`, then again with `--exit-code 1` as the gate.

**Unit tests.** pytest, results published as JUnit XML. Runs before security scanning so broken code stops early.

**SAST.** Semgrep with `p/python`. The report is written first (`|| true`), then the gate runs `semgrep scan --config p/python --error app/`; `--error` makes Semgrep exit non-zero when it reports findings (the Jenkinsfile comment calls these ERROR-level; confirm exact severity behavior in a break-and-fix test). Reads source without running it. Build #8: 0 findings, 1 file, 151 rules.

**Dependency scan.** pip-audit against `requirements.txt` (PyPA advisory database and OSV). Runs before the image build because it is fast and the build is slow.

**Config scan.** `trivy config .` scans the repository recursively (Dockerfiles and Kubernetes manifests among other config files); the report is written first, then the gate fails on HIGH/CRITICAL only. Both Dockerfile and manifests are scanned because an insecure manifest can undo a secure Dockerfile. Typical findings: root containers, missing resource limits, writable root filesystem, privilege escalation, missing seccomp.

**Build image.** `docker build --pull -t devsecops-app:8 app/`. `--pull` fetches the newest patch of the base image each build; the tag is the build number, never `latest`.

**Image scan.** Trivy image scan, `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`. Catches OS-package CVEs (libc, openssl, libexpat…) that pip-audit cannot see. Unfixed CVEs are reported in `trivy-image.json` but do not block.

**SBOM.** Trivy CycloneDX output to `reports/sbom.cdx.json`. It has no findings gate — it only produces evidence (a tool error would still fail the stage). When a new CVE is announced, search the SBOM to see whether the image is affected.

**Deploy to dev.**

```bash
docker save devsecops-app:8 | docker exec -i devsecops-control-plane \
    ctr -n k8s.io images import --all-platforms -

sed -e 's/BUILD_TAG/8/g' k8s/deployment.yaml | kubectl apply -n dev -f -
kubectl apply -n dev -f k8s/service.yaml
kubectl rollout status deployment/devsecops-app -n dev --timeout=120s
```

`sed` substitutes `BUILD_TAG` in the stream; the file on disk is unchanged. Rollout blocks until both pods pass readiness; failure to finish in 120s fails the build.

**Smoke test.** See [section 11](#11-failure-3--smoke-test-deep-dive).

**Approve prod.**

```groovy
input message: "Deploy build #8 to prod?", ok: 'Approve'
```

15-minute timeout; a timeout gives ABORTED (code was fine), not FAILED. This is continuous delivery, not continuous deployment. Approval is informed because the same scanned image has already passed the dev smoke test.

**Deploy to prod.**

```bash
sed -e 's/BUILD_TAG/8/g' k8s/deployment.yaml | kubectl apply -n prod -f -
kubectl apply -n prod -f k8s/service.yaml
kubectl rollout status deployment/devsecops-app -n prod --timeout=120s
```

The image is already in containerd from the dev deploy.

**Pipeline options.** `timestamps()` prefixes every log line, and `buildDiscarder(logRotator(numToKeepStr: '10'))` keeps logs and artifacts for the last 10 builds only.

**Post block.** Runs on every build: `security_summary.py` writes `reports/security-summary.md` and appends a row to `/var/jenkins_home/security-trends.csv`; everything under `reports/` is archived; the workspace is cleaned.

Archived artifacts: `trivy-secrets.json`, `semgrep.json`, `pip-audit.json`, `trivy-config.json`, `trivy-image.json`, `sbom.cdx.json`, `security-summary.md`, `pytest-results.xml`.

### Why each scan type matters

- **Secret scanning:** a secret pushed to a public repo is effectively public, and stays in git history even if deleted in the next commit.
- **SAST:** catches patterns such as string-built SQL, `eval()`, hardcoded passwords, and insecure deserialization without running the app.
- **Dependency scanning:** most of what runs is dependency code, not code you wrote. Unpinned versions (`flask>=3.0`) would let pip-audit pass while a vulnerable version is installed.
- **Config scanning:** a well-written app can be made insecure by its Dockerfile or manifest.
- **Image scanning:** covers the OS layer in the base image.
- **SBOM:** answers "am I affected?" without a rebuild and rescan.

---

## 4. Application notes

`app/app.py` is a minimal Flask service — the pipeline is the project, not the app.

| Route | Returns |
|-------|---------|
| `/` | `{"message": "DevSecOps demo service", "version": APP_VERSION}` |
| `/health` | `{"status": "ok"}` with 200 |
| `/version` | `{"version": APP_VERSION}` |

`APP_VERSION` is injected as an environment variable at deploy time (the build number in the cluster; `dev` locally).

`/health` is used in three places: the readiness probe, the liveness probe, and the pipeline smoke test. A container starting is not the same as an app working.

**Dependencies:** `flask==3.1.3`, `gunicorn==23.0.0`, both pinned. `flask==3.0.3` was deliberately used as the known-vulnerable version for the controlled test in Build #4, which it failed as intended.

**Tests** (`app/tests/test_app.py`): `test_health_returns_ok` (200, `{"status": "ok"}`) and `test_index_reports_version` (200, `version` key present). They run before any image is built.

---

## 5. Dockerfile line by line

```dockerfile
# Stage 1: build — installs dependencies into /install
FROM python:3.12-slim-bookworm AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: runtime — only what is needed to run
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=build /install /usr/local
COPY app.py .
USER 10001
EXPOSE 8080
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--worker-tmp-dir", "/tmp", "app:app"]
```

| Line | Purpose |
|------|---------|
| `FROM ... AS build` | Names a temporary stage used only to install dependencies |
| `pip install --no-cache-dir --prefix=/install` | Installs into an isolated folder that can be copied wholesale; no pip cache keeps the layer small |
| Second `FROM` | Fresh image; build tooling and caches never reach it (fewer packages, fewer CVEs) |
| `useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin` | Non-root user with no home and no shell |
| `COPY --from=build /install /usr/local` | Only installed packages cross over |
| `USER 10001` | Everything after runs non-root; Kubernetes also enforces `runAsNonRoot` |
| `CMD gunicorn ... --worker-tmp-dir /tmp` | Production server; `/tmp` is a writable `emptyDir` because the root filesystem is read-only in Kubernetes |

Flask's dev server is single-threaded and carries debug features that are a security risk; gunicorn gives multiple workers and proper signal handling.

---

## 6. Kubernetes manifests

### Namespaces

`dev` and `prod` are logical separations in one cluster. A Service in `dev` is not reachable from `prod` by its short name.

### Deployment (key fields)

```yaml
spec:
  replicas: 2
  selector:
    matchLabels:
      app: devsecops-app
  template:
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - image: devsecops-app:BUILD_TAG    # replaced by sed at deploy time
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
```

| Setting | What it prevents |
|---------|-----------------|
| `runAsNonRoot: true` | Pod refuses to start if the image runs as root |
| `runAsUser: 10001` | Process runs as the non-root appuser |
| `readOnlyRootFilesystem: true` | Attacker cannot write tools or modify files |
| `allowPrivilegeEscalation: false` | Process cannot gain more privileges than it started with |
| `capabilities: drop: ALL` | No Linux capabilities |
| `seccompProfile: RuntimeDefault` | Kernel syscall filter blocks dangerous operations |
| `automountServiceAccountToken: false` | No Kubernetes API token available to steal |
| `runAsGroup: 10001` | Process group is also non-root |
| `resources.requests` 50m CPU / 64Mi, `limits` 250m CPU / 128Mi | One pod cannot starve the node of CPU or memory |
| `imagePullPolicy: IfNotPresent` | Uses the image imported into containerd; no registry pull |

### Service

ClusterIP on port 80, `targetPort` 8080, selector `app: devsecops-app`. It is reachable only inside the cluster. The smoke test curls `http://devsecops-app/health`; cluster DNS resolves the name and the Service load-balances across the 2 pods.

### Rollout and readiness

`kubectl rollout status deployment/devsecops-app -n dev --timeout=120s` blocks until both pods are ready. The readiness probe calls `/health` every 5 seconds starting 3 seconds after pod start, so the pipeline cannot reach the smoke test until the app is actually ready.

### Kind

Kind runs a real Kubernetes cluster as Docker containers. Here: cluster `devsecops`, one node `devsecops-control-plane`.

---

## 7. Environment setup errors

### kind cluster named my-cluster instead of devsecops
**What I saw:** `kind get clusters` returned `my-cluster` instead of `devsecops`.
**What caused it:** The cluster was created earlier during environment testing with the wrong name.
**How I fixed it:** `kind delete cluster --name my-cluster` then `kind create cluster --name devsecops`.

### kubectl connection refused to 127.0.0.1:46835
**What I saw:** `kubectl get nodes` returned `connection refused`.
**What caused it:** The `my-cluster` kind cluster had its API server port binding go stale after a Docker Desktop restart. The kind containers were still running but the API server was unreachable.
**How I fixed it:** Deleted the broken cluster and created `devsecops` fresh.

---

## 8. Jenkins image build errors

### Trivy install script failed — exit code 1
**What I saw:** Docker build failed at the Trivy install step with exit code 1.
**What caused it:** Two issues combined:
1. The earlier docs specified Trivy `v0.56.2`, which does not exist on GitHub — the API returns `Not Found`.
2. `ARG` variables were not expanding inside piped curl commands in Docker BuildKit.

**How I fixed it:** Replaced the install script with a direct tarball download using a hardcoded URL. Updated to `v0.75.0`, which is confirmed to exist.

### Jenkins 2.462.3 plugin version mismatch
**What I saw:** After first-time plugin install, every plugin failed to load with "Jenkins 2.479+ or higher required".
**What caused it:** The base image in `jenkins/Dockerfile` was `2.462.3-lts-jdk17`; current plugin versions require Jenkins 2.479+.
**How I fixed it:** Updated the base image to `jenkins/jenkins:2.504.3-lts-jdk17`.

---

## 9. Failure 1 — Flask CVE (Build #4)

**What I saw:** Build #4 failed at the Dependency scan stage:

```
flask 3.0.3   PYSEC-2026-2151   fix: 3.1.3
```

**What caused it:** I intentionally used a known vulnerable dependency version in a controlled test: `app/requirements.txt` pinned Flask at `3.0.3`, which has a published vulnerability. The aim was to verify that pip-audit detects the CVE and stops the pipeline before deployment. pip-audit identified it and the gate failed the build as designed. Nothing deployed.

**Terminology:** a CVE (or PYSEC advisory) is a *known software vulnerability* in a published version of a package. It is not malware, a virus, or malicious code; Flask `3.0.3` was a normal, legitimate release with a documented flaw.

**Flow:** Known vulnerable dependency → pip-audit detects the CVE → dependency scan fails → pipeline stops → nothing deploys → dependency is upgraded → pipeline passes.

**What this demonstrates:** The gate working correctly — a vulnerable dependency was caught before an image was built and before anything touched a cluster.

**How I fixed it:** Updated `app/requirements.txt` to `flask==3.1.3`. The next build passed the SCA gate with `No known vulnerabilities found`. Commit: `Fix PYSEC-2026-2151: upgrade flask 3.0.3 to 3.1.3`.

---

## 10. Failure 2 — Kind image loading deep dive

**What I saw:** Builds #5 and #6 failed at Deploy to dev:

```
ERROR: failed to detect containerd snapshotter
```

### Environment

```
Your machine (WSL2)
  └── Docker Desktop
        ├── Jenkins container       ← runs the pipeline
        │     └── mounts /var/run/docker.sock
        └── devsecops-control-plane ← the Kind cluster node
              └── containerd        ← manages pods inside Kubernetes
```

Jenkins and the Kind node are both containers on the same Docker daemon (socket mount — Docker-outside-of-Docker rather than a nested daemon).

### What was confirmed to work

- Jenkins can run `docker` commands
- Jenkins can `docker exec` into the Kind node
- containerd and `ctr` are healthy inside the node

### Root-cause explanation (working theory)

`kind load docker-image` works in steps internally: connect to Docker to export the image, reach the node via `docker exec`, detect which containerd snapshotter (`overlayfs` or `fuse-overlayfs`) the node uses, then import. The failure message names the snapshotter detection step, and a direct `docker save | ctr import` from Jenkins succeeded, so the failure is specific to `kind load` when run from inside the Jenkins container. This explanation is inferred from the error text and the diagnostics below; it is not based on reading the Kind source.

### Failed approach

Setting `KIND_EXPERIMENTAL_PROVIDER=docker` was tried (commit `Fix: add KIND_EXPERIMENTAL_PROVIDER=docker for kind load inside Jenkins`). It did not fix the error.

### Diagnostic commands

```bash
# 1. Jenkins is a container with the Docker socket mounted
docker inspect jenkins --format '{{.HostConfig.Binds}}'
# [jenkins_home:/var/jenkins_home /var/run/docker.sock:/var/run/docker.sock]

# 2. Jenkins can run Docker commands
docker exec jenkins docker ps

# 3. Jenkins can exec into the Kind node
docker exec jenkins docker exec devsecops-control-plane hostname
# devsecops-control-plane

# 4. containerd is healthy inside the Kind node
docker exec devsecops-control-plane ctr version
# Server Version: v2.0.2

# 5. Direct image import from Jenkins into the Kind node
docker exec jenkins bash -c "docker save devsecops-app:8 | \
  docker exec -i devsecops-control-plane ctr -n k8s.io images import --all-platforms -"
# Importing elapsed: 2.3s — SUCCESS

# 6. Image visible to Kubernetes
docker exec devsecops-control-plane ctr -n k8s.io images ls | grep devsecops
# docker.io/library/devsecops-app:8 ... linux/amd64
```

### Working solution

```bash
docker save ${IMAGE_REF} | docker exec -i devsecops-control-plane \
    ctr -n k8s.io images import --all-platforms -
```

| Part | What it does |
|------|-------------|
| `docker save ${IMAGE_REF}` | Exports the image as a tar stream to stdout |
| `\|` | Pipes the stream to the next command |
| `docker exec -i devsecops-control-plane` | Runs inside the Kind node; `-i` keeps stdin open for the pipe |
| `ctr -n k8s.io` | containerd CLI in the `k8s.io` namespace |
| `images import --all-platforms -` | Imports from stdin, keeping all platform manifests |

### Why `-n k8s.io` is required

containerd namespaces isolate images between consumers; they are separate from Kubernetes namespaces. Kubernetes (via the CRI plugin) reads images only from `k8s.io`. Importing without `-n k8s.io` lands the image in the `default` containerd namespace: `ctr images ls` shows it, but pods fail with `ImagePullBackOff` or `ErrImageNeverPull`. With `-n k8s.io` the kubelet finds it with no registry.

### Lessons

`kind load docker-image` is designed to run on the host. When Jenkins runs in a container and must put images into Kind, bypass `kind load` and use `docker save | ctr -n k8s.io images import`.

In production this problem does not exist: images are pushed to a registry (ECR, ACR, GCR, Docker Hub) and Kubernetes pulls from it.

---

## 11. Failure 3 — Smoke test deep dive

**What I saw:** Deploy to dev failed at the smoke test:

```
--rm should only be used for attached containers
```

### Original command

```bash
kubectl run smoke-test \
    --image=curlimages/curl:8.5.0 \
    --restart=Never \
    --rm \
    -n dev \
    --timeout=60s \
    -- curl -sf http://devsecops-app/health
```

### Cause

The rollout had already succeeded; both pods were running. Only the smoke test command failed. `--rm` deletes the pod after exit but only works when kubectl is attached to the pod's stdin/stdout. Jenkins shell steps are non-interactive, so kubectl detected no attachment and refused.

### Fix — create / wait / logs / delete

```bash
# Create the pod — curl hits /health
kubectl run smoke-test --image=curlimages/curl:8.5.0 \
    --restart=Never -n dev -- curl -sf http://devsecops-app/health

# Wait for Succeeded (curl exited 0 = /health returned 200)
kubectl wait pod/smoke-test -n dev \
    --for=jsonpath='{.status.phase}'=Succeeded --timeout=30s

# Print the response to the build log
kubectl logs smoke-test -n dev

# Always clean up
kubectl delete pod smoke-test -n dev
```

### Why it works in CI

Each step is independent. `curl -sf` exits non-zero on a non-200 response, the pod phase becomes `Failed`, `kubectl wait` times out, and the build fails. Cleanup is explicit rather than tied to an attached session.

**Result:** `{"status":"ok"}` printed to the build log, pod deleted, build continued to Approve prod.

### What a passing smoke test proves

| Proven | Why it matters |
|--------|---------------|
| Cluster DNS resolved `devsecops-app` | Service name is registered |
| Service routed to a healthy pod | Labels and selectors are correct |
| Pod answered on port 8080 | App is running, not just the container |
| `/health` returned HTTP 200 | Readiness endpoint works |
| Valid JSON returned | Flask app is functional |

**Lesson:** `kubectl run --rm` is a convenience for interactive shells. In CI, use explicit create/wait/delete for control over each step and cleaner logs.

---

## 12. security_summary.py troubleshooting

**What I saw:** The post-build summary script printed an error but did not fail the build (the script catches exceptions by design):

```
[summary] ERROR: 'str' object has no attribute 'get'
```

**What caused it:** `parse_pip_audit` expected pip-audit's JSON to be a bare list (`[{...}, {...}]`). pip-audit 2.7.3 outputs a dict with a `dependencies` key (`{"dependencies": [{...}]}`). The function iterated the top-level dict and called `.get()` on string keys.

**How I fixed it:** Normalise before parsing (commit `Fix: ... fix pip-audit JSON dict format in summary script`):

```python
if isinstance(data, dict):
    packages = data.get("dependencies", []) or []
else:
    packages = data or []  # legacy bare list format
```

**Lesson:** Pin tool versions and read changelogs on upgrade. A scanner's JSON schema change silently breaks downstream parsers. Test parsers against real tool output, not assumed formats.

### What the script produces

- `reports/security-summary.md` — human-readable summary of per-stage results
- `/var/jenkins_home/security-trends.csv` — one row per build, to track finding counts over time

A blocked build still has all its reports, which is how you explain why it was blocked.

**Scope (from reading `scripts/security_summary.py`):**

- Reads `trivy-secrets.json`, `semgrep.json`, `pip-audit.json`, `trivy-config.json`, and `trivy-image.json`.
- Writes a "Status at a Glance" table (secrets, SAST, dependency, config, image) plus one section per scanner; tables are capped at 20 rows, or 30 for the image scan, with fixable HIGH/CRITICAL listed first.
- The PASS/FAIL shown is derived from the findings in those JSON files, not from Jenkins stage results.
- It does **not** cover pytest results, the SBOM, the smoke test, or the deploy and approval stages.
- The trend CSV has 17 columns: timestamp, build number, build URL, and counts for secrets, Semgrep, pip-audit, config (by severity), and image (by severity, plus fixable HIGH/CRITICAL).
- The script always exits 0 and prints `[summary] ERROR: ...` on failure instead of failing the build.
- **Fixed bug (severity counts):** the parsers store each finding's severity under the key `severity`, but `severity_counts()` read `Severity`, so every finding was counted as UNKNOWN. Summaries and trend rows for builds up to #9 and `nightly-1` showed `CRITICAL=0, HIGH=0, MEDIUM=0, LOW=0` while still reporting the right total (284). The real build #9 image counts are CRITICAL 2, HIGH 61, MEDIUM 112, LOW 108, and config has 3 LOW. The pass/fail gates were never affected: they use Trivy's own exit code and the separate `fixable HIGH/CRITICAL` count, which read the correct key. `severity_counts()` now defaults to `severity`. Trend rows written before the fix have wrong severity columns.

---

## 13. Troubleshooting playbook

| Problem | Symptoms | Likely cause | Diagnostic command | Fix |
|---------|----------|--------------|--------------------|-----|
| Git checkout failure | `Unable to find Jenkinsfile` | URL missing `.git`, wrong branch, commit not pushed | `git log --oneline origin/<branch>` | Add `.git`; push commits; check branch name |
| Jenkins plugin errors | Red banners on dashboard | Jenkins too old for plugins | `docker exec jenkins java -jar /usr/share/jenkins/jenkins.war --version` | Update base image version in `jenkins/Dockerfile` |
| Unit test failure | Stage red, pytest failure | App code broken | Read pytest output | Fix test or code |
| Semgrep finding | Stage red, ERROR reported | Dangerous pattern in `app/` | `semgrep scan --config p/python --error app/` | Fix flagged code |
| Vulnerable dependency | pip-audit lists CVE | Pinned version has CVE | `pip-audit -r app/requirements.txt` | Upgrade package |
| Config misconfiguration | Trivy HIGH/CRITICAL | Dockerfile or manifest issue | `trivy config .` | Fix flagged setting |
| Docker build failure | `docker build` error | Syntax, network, missing file | Read build output | Fix Dockerfile or network |
| Docker socket permission | `permission denied: /var/run/docker.sock` | Jenkins not running as root | `docker inspect jenkins --format '{{.HostConfig.UsernsMode}}'` | Re-run container with `-u root` |
| Kind image loading failure | `failed to detect containerd snapshotter` | `kind load` does not work from inside a container | See [section 10](#10-failure-2--kind-image-loading-deep-dive) | `docker save \| ctr -n k8s.io images import` |
| kubectl auth failure | `connection refused` / `unauthorized` | Kubeconfig points at wrong address | `kubectl --kubeconfig /tmp/k get nodes` from Jenkins | Regenerate with `--internal` |
| Rollout timeout | `timed out waiting for rollout` | Pods not starting; readiness failing | `kubectl get pods -n dev`, `kubectl describe pod <name> -n dev`, `kubectl logs <name> -n dev` | Check pod logs |
| ImagePullBackOff | Pods stuck | Image not in `k8s.io` namespace | `docker exec devsecops-control-plane ctr -n k8s.io images ls \| grep devsecops` | Re-run import |
| CrashLoopBackOff | Pods restart repeatedly | App crashes on startup | `kubectl logs <pod> -n dev --previous` | Fix the app error |
| Service not reachable | Smoke test curl fails | Labels don't match selector, wrong port | `kubectl describe svc devsecops-app -n dev`, `kubectl get endpoints -n dev` | Match pod labels to selector |
| Smoke test `--rm` error | `--rm should only be used for attached containers` | Jenkins stdin not attached | See [section 11](#11-failure-3--smoke-test-deep-dive) | create/wait/logs/delete |
| Approval timeout | Build ABORTED after 15 min | Nobody approved | Check build page | Approve in time or re-run |

---

## 14. Design decisions and production tradeoffs

| Decision | Lab choice | Why it works for the lab | Production alternative | Tradeoff |
|----------|-----------|--------------------------|------------------------|----------|
| Kubernetes platform | Kind | Zero cost, offline, real API | EKS, AKS, GKE, on-prem | Kind has no HA, no persistent storage class, no auto-scaling |
| Jenkins deployment | Docker container on a laptop | Simple, portable, easy to reset | Dedicated VM or Kubernetes deployment, multiple agents | Single point of failure; competes for laptop resources |
| Docker socket mounting | `/var/run/docker.sock` into Jenkins | Simplest way to `docker build` | Kaniko, Buildah, dedicated build agents | Socket gives Jenkins root-equivalent access to the host |
| Image delivery | `docker save \| ctr -n k8s.io images import` | No registry needed | Push to ECR/ACR/GCR | Local import does not work across multiple nodes |
| Dev/prod separation | Two namespaces, one cluster | Easy; demonstrates concept | Separate clusters, accounts, or subscriptions | Shared control plane and node resources; a compromise can cross namespaces |
| Kubeconfig credential | Secret file in Jenkins | Encrypted at rest in Jenkins | Workload identity (IRSA, GKE/AKS Workload Identity) | A static kubeconfig can be extracted if Jenkins is compromised |
| Secrets management | Jenkins credential store | Built in | Vault, AWS Secrets Manager, Azure Key Vault | Not designed for rotation or audit trails |
| Production promotion | Manual `input` approval | Explicit and simple | GitOps with Argo CD | GitOps gives a full audit trail and declarative state |
| Build location | Jenkins controller | No agent setup | Dedicated agents | A malicious build step could read Jenkins credentials |

In this lab, `dev` and `prod` are namespaces in the same Kind cluster. In a real program they would typically be separate clusters, cloud accounts, or subscriptions.

---

## 15. Build #8 final result

```
Finished: SUCCESS
```

| Stage | Result | Notes |
|-------|--------|-------|
| Secrets scan | ✅ | 0 secrets |
| Unit tests | ✅ | 2/2 passed |
| SAST | ✅ | 0 findings (151 rules on app.py) |
| Dependency scan | ✅ | No known vulnerabilities (flask 3.1.3) |
| Config scan | ✅ | 0 HIGH/CRITICAL misconfigurations; 3 LOW (DS-0026 in both Dockerfiles, KSV-0110 in `deployment.yaml`) — these did not show in the summary until the severity-counting fix below |
| Build image | ✅ | devsecops-app:8, python:3.12-slim-bookworm |
| Image scan gate | ✅ | 0 fixable HIGH/CRITICAL CVEs |
| SBOM | ✅ | sbom.cdx.json generated |
| Deploy to dev | ✅ | 2 replicas rolled out |
| Smoke test | ✅ | `{"status":"ok"}` from /health |
| Approve prod | ✅ | Approved by Eman Kwe |
| Deploy to prod | ✅ | 2 replicas rolled out |
| Security summary | ✅ | security-summary.md written, trend row appended |

---

## 16. Interview study notes

These are study scripts. They describe only what has been done. The break-and-fix tests are not completed and must not be presented as done. The nightly rescan is completed and verified (build #1), apart from an unobserved 02:00 scheduled firing.

### 30-second version

"I built an automated security pipeline that takes code from GitHub and deploys it to Kubernetes. Before anything deploys, it runs secret scanning, unit tests, static code analysis, dependency checking, infrastructure config scanning, and container image scanning. If any gate fails, deployment stops. A person approves the production release."

### 60-second version

"The project is a Jenkins CI/CD pipeline with security checks in every stage. On a build, Jenkins pulls from GitHub, runs Trivy secret scanning, pytest, Semgrep, pip-audit, and Trivy config scanning. Then it builds a Docker image, scans it for OS-level CVEs, generates an SBOM, deploys to a dev Kubernetes namespace, runs an automated health check, and waits for a human to approve production. Any failing gate stops the build. It runs on one machine using Kind and Docker. One real gate failure along the way was a vulnerable Flask version caught by pip-audit in Build #4."

### 2-minute technical version

"The pipeline has 11 stages in a declarative Jenkinsfile, ordered cheapest-first to fail fast.

Stage 1 is a Trivy secrets scan of the repo. Stage 2 is pytest. Stage 3 is Semgrep with `p/python`. Stage 4 is pip-audit — this caught the known CVE in the version I intentionally used for the test: flask 3.0.3 has PYSEC-2026-2151; the build failed, I upgraded to 3.1.3, and it passed.

Stage 5 is a Trivy config scan of the Dockerfiles and manifests — both, because an insecure manifest can undo a secure Dockerfile. Stage 6 builds the image with `--pull`. Stage 7 is a Trivy image scan that fails on HIGH or CRITICAL CVEs that have a fix and ignores unfixed ones.

Stage 8 generates a CycloneDX SBOM. Stage 9 deploys to dev, waits for rollout, and runs a curl-pod smoke test against `/health`. Stage 10 is a human approval gate. Stage 11 deploys the same image to prod.

The interesting technical problem was image loading. From inside the Jenkins container, `kind load docker-image` failed with 'failed to detect containerd snapshotter'. I confirmed Docker socket access, exec access into the Kind node, and containerd health, then showed that `docker save | docker exec -i ... ctr -n k8s.io images import` worked. The `-n k8s.io` matters because Kubernetes only reads images from that containerd namespace."

### Hardest problem

"The hardest problem was getting the image into the Kind cluster from inside a Jenkins container.

`kind load docker-image` failed with `ERROR: failed to detect containerd snapshotter`, which was not specific enough to point at a cause.

I worked through it step by step. I confirmed Jenkins had the Docker socket and could run Docker commands, that it could `docker exec` into the Kind node, and that containerd and `ctr` were healthy there. So connectivity was fine and the problem was specific to `kind load`. My working explanation was that the snapshotter detection step in `kind load` doesn't work from inside the Jenkins container. I tried `KIND_EXPERIMENTAL_PROVIDER=docker` and it didn't help.

The fix was to bypass `kind load`: `docker save` streams the image as a tar, `docker exec -i` pipes it into the node, and `ctr -n k8s.io images import` puts it in the namespace Kubernetes reads. Knowing why `-n k8s.io` matters is what separates understanding the fix from guessing it."

### What I would improve for production

"Four things first. Replace Kind with a managed Kubernetes service for a managed control plane, auto-scaling, and persistent storage. Add a container registry so Kubernetes pulls images rather than having them imported into one node. Replace the Docker socket mount with Kaniko or Buildah so builds do not have root-equivalent host access. Replace the static kubeconfig with workload identity, such as IRSA on EKS, so there is no long-lived credential to steal."

### Likely follow-up questions

- *Why scan config before building the image?* It is faster than the build, and a bad Dockerfile is caught before spending minutes.
- *Why `--ignore-unfixed`?* There is nothing to fix until upstream ships a patch; they remain visible in `trivy-image.json`.
- *Why continuous delivery, not deployment?* A person decides when production changes; approval follows dev validation.
- *What would you say is not done?* The break-and-fix tests are planned, not completed. The nightly rescan is done and verified as a Jenkins job, but I have not watched the 02:00 schedule fire.

---

## 17. Lessons learned

**Troubleshoot layer by layer.** The image-loading failure looked like a Kubernetes problem and then a Docker socket problem. Working outside-in — Docker socket, exec access, containerd, namespace — located the cause.

**Distinguish build problems from deployment problems.** When the smoke test failed with `--rm ...`, the deployment had already succeeded. Checking pod status first narrows the diagnosis.

**Validate assumptions with commands.** `kind load` failing does not mean Docker, kind, or containerd is broken. Each assumption needs a command to test it.

**Security gates should be seen failing.** Build #4 showed the dependency gate working. The other gates have not been deliberately exercised yet; break-and-fix testing (fake secret, misconfigured manifest) is planned. The dependency gate was already exercised in Build #4 with an intentionally vulnerable dependency.

**Pinned versions matter.** Trivy `v0.56.2` did not exist and `ARG` values did not expand in piped curl commands under BuildKit. Both produced misleading errors; hardcoding versions in download URLs solved both.

**Local lab design differs from production.** Docker socket mounting, controller builds, Kind, and a static kubeconfig each have a documented production alternative in [section 14](#14-design-decisions-and-production-tradeoffs).

---

## 18. Planned / future work

**Completed and verified:**

- **Nightly rescan** of the production image. Jenkins job `prod-nightly-rescan` (Pipeline script from SCM, `jenkins/Jenkinsfile.rescan`, branch `jpd-20261012`) ran as build #1 on 2026-10-16 with result SUCCESS. Console shows: `kind-kubeconfig` loaded (masked), prod image read from the deployment (`devsecops-app:9`, matching `kubectl get deployment`), Trivy DB update, full scan to `reports/trivy-image.json`, HIGH/CRITICAL fixable gate clean, `security_summary.py` ran, and a `nightly-1` row was appended to `security-trends.csv` (`image_total` 284, matching build #9). Archived: `security-summary.md`, `trivy-image.json`. The summary warns that the secrets, config, pip-audit and semgrep reports are absent; that is expected, since the rescan only scans the image. Cron `0 2 * * *` is in the Jenkinsfile and registered on the job as a `TimerTrigger`; the 02:00 firing itself was not waited for. An earlier bug (rescan wrote `trivy-image-rescan.json`, which the summary script does not read) was fixed in commit `20cdb1f`.

**Not completed:**

- **Break-and-fix tests** for each gate: fake secret, misconfigured manifest, vulnerable base image (the dependency gate is already proven by the intentional test in Build #4)

**Further improvements:**

| Improvement | What it adds | Priority |
|-------------|-------------|----------|
| Container registry (ECR/ACR/GCR) | Image reuse across nodes, pull-based deployment, registry scanning | High |
| Managed Kubernetes (EKS/AKS/GKE) | Production-grade cluster, auto-scaling, persistent storage | High |
| Kaniko or Buildah | Removes Docker socket dependency | High |
| Workload identity (IRSA / Workload Identity) | No long-lived kubeconfig | High |
| Argo CD or Flux | GitOps audit trail, drift detection | Medium |
| External secrets manager | Rotation and audit | Medium |
| Prometheus + Grafana | Metrics, dashboards, alerting | Medium |
| OPA / Kyverno | Admission-time policy | Medium |
| Cosign | Image signing | Medium |
| SonarQube or CodeQL | Deeper SAST | Medium |
| OWASP ZAP | Dynamic testing of the dev deployment | Medium |
| Helm | Cleaner than `sed` substitution | Low |
| Terraform | Infrastructure as code | Low |

---

## 19. Screenshots checklist

Eight are captured and committed in `images/` (ticked below); the rest are pending. Capture them from the working project before it is shut down.

- [ ] **Architecture diagram** — `images/architecture-diagram.png` — GitHub, Jenkins, scan stages, Docker, Kind, dev, approval gate, prod
- [x] **Jenkins full successful pipeline** — `images/jenkins-success-1.png`, `images/jenkins-success-2.png` — Stage View for build #8, all stages green
- [ ] **Manual production approval prompt** — `images/jenkins-prod-approval.png` — "Deploy build #8 to prod?"
- [ ] **Security summary report** — `images/security-summary.png` — `reports/security-summary.md` from build #8
- [x] **Trivy image scan result** — `images/trivy-image-scan.png` — summary JSON: 284 total, `fixable_high_crit: 0`
- [x] **Kubernetes dev pods** — `images/k8s-dev-pods.png` — `kubectl get pods,svc -n dev`
- [ ] **Kubernetes production pods** — `images/k8s-prod-pods.png` — `kubectl get pods,svc -n prod`
- [x] **Production version verification** — `images/prod-version-check.png` — `curl -s localhost:9090/version` → `{"version":"8"}`
- [x] **Smoke test success** — `images/smoke-test-success.png` — `{"status":"ok"}` and `pod "smoke-test" deleted`
- [ ] **Application health endpoint** — `images/health-endpoint.png` — `/health` response
- [ ] **Jenkins credentials page** — `images/jenkins-credentials.png` — `kind-kubeconfig` by ID; do not show contents
- [x] **Build #8 checkout revision** — `images/build8-checkout-revision.png` — console showing the checked-out commit
- [x] **Nightly rescan** — `images/nightly-rescan.png` — `prod-nightly-rescan` build #1 SUCCESS
- [ ] **Non-root / read-only verification** — `images/prod-nonroot-readonly.png` — `kubectl -n prod exec deploy/devsecops-app -- id` shows UID 10001; `touch /app/test` fails with `Read-only file system`
- [ ] **Kind cluster nodes** — `images/kind-cluster.png` — `kubectl get nodes` and `kubectl get ns dev prod`

---

## 20. Material moved from the README

The README was shortened into the portfolio story. These pieces used to live there and are kept here in full.

### Pipeline stages and gates at a glance

| # | Stage | Tool | Gate |
|---|-------|------|------|
| 1 | Secrets scan | Trivy fs | Any secret fails |
| 2 | Unit tests | pytest | Any failure fails |
| 3 | SAST | Semgrep `p/python` | Gate runs `semgrep scan --error`: a finding fails the build |
| 4 | Dependency scan | pip-audit | Any known CVE fails |
| 5 | Config scan | Trivy config | HIGH/CRITICAL fails |
| 6 | Build image | Docker (`--pull`) | Build error fails |
| 7 | Image scan | Trivy image | Fixable HIGH/CRITICAL fails (`--ignore-unfixed`) |
| 8 | SBOM | Trivy CycloneDX | No findings gate; produces evidence only |
| 9 | Deploy to dev + smoke test | docker save/ctr, kubectl | Rollout or smoke test failure fails |
| 10 | Approve prod | Jenkins `input` | 15-min timeout → ABORTED |
| 11 | Deploy to prod | kubectl | Rollout failure fails |
| post | Security summary, archive reports, clean workspace | `security_summary.py` | Runs on every build |

### Security decisions, full list

- **Order: cheapest check first.** Secrets and tests run before the image build, so failures there cost little.
- **Two scanners for dependencies.** pip-audit covers Python packages; Trivy image scan covers OS packages pip-audit never sees.
- **Pinned versions.** `requirements.txt` is pinned to exact versions so pip-audit can look up CVEs reliably. Image tags are build numbers, never `latest`.
- **`--ignore-unfixed`.** Only findings with an available fix block the build; unfixed ones are still reported in `trivy-image.json`.
- **Non-root, minimal image.** Multi-stage build, UID 10001, no shell, no home directory, gunicorn instead of the Flask dev server.
- **Hardened pod spec.** `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, drop ALL capabilities, `seccompProfile: RuntimeDefault`, no service account token, and CPU/memory requests and limits (50m/64Mi requested, 250m/128Mi limit).
- **Build retention.** Jenkins keeps the last 10 builds and their archived reports.
- **Human approval for prod.** Continuous delivery with a 15-minute timeout; a timeout is ABORTED, not FAILED.
- **Reports on every build.** A blocked build still archives its scanner output so the block can be explained.
- **Empty `.trivyignore`.** Accepted risks would need a CVE ID, expiry, reason, approver, and ticket.

### Lab shortcuts

| Shortcut | Why it is fine in a lab | Production alternative |
|----------|------------------------|------------------------|
| Docker socket mounted into Jenkins, `-u root` | Simplest way to run `docker build` | Kaniko, Buildah, or dedicated build agents |
| Kind instead of a managed cluster | Free, offline, real Kubernetes API | EKS, AKS, GKE |
| No registry; `docker save \| ctr import` | Works for one local node | ECR, ACR, GCR |
| `dev` and `prod` are namespaces in one cluster | Demonstrates the concept | Separate clusters or accounts |
| Static kubeconfig credential | Simple | Workload identity |
| Jenkins credential store only | Built in | Vault or a cloud secrets manager |
| Pipeline runs on the controller | No agent setup | Dedicated agents |
| Manual `input` approval | Easy to understand | GitOps (e.g. Argo CD) |

The full tradeoff table is in section 14.

### Honest scope

**What this project demonstrates:** a working scan-build-deploy-approve pipeline on a single machine, with scanners, gates, a hardened image and pod spec, a smoke test, per-build reporting, and a verified nightly rescan job. Build #8 completed end to end.

**What it does not demonstrate:**
- Break-and-fix tests for the fake-secret, misconfigured-manifest and base-image gates (**planned, not completed**)
- Multi-node, multi-cluster, or cloud deployment
- A container registry, image signing, or policy enforcement
- Production-grade secrets management or build isolation
- Monitoring or alerting

### Evidence captions (screenshots committed in `images/`)

| File | What it shows |
|------|---------------|
| `jenkins-success-1.png` | Build #8 pipeline graph, Checkout SCM through Image scan gate, all green |
| `jenkins-success-2.png` | Build #8 remaining stages: SBOM, Deploy to dev, Approve prod (6m 17s), Deploy to prod, Post Actions |
| `build8-checkout-revision.png` | Build #8 console: checked out revision `bf73cba` of branch `jpd-20261012` |
| `smoke-test-success.png` | Dev rollout, smoke-test pod returns `{"status":"ok"}` and is deleted |
| `trivy-image-scan.png` | Trivy image scan summary: 284 findings (2 CRITICAL, 53 HIGH), `fixable_high_crit: 0` |
| `k8s-dev-pods.png` | `kubectl -n dev get pods,svc`: 2 pods Running, ClusterIP service on port 80 |
| `prod-version-check.png` | Prod `/version` via port-forward returns `{"version":"8"}` (Build #8) |
| `nightly-rescan.png` | `prod-nightly-rescan` build #1 SUCCESS with `security-summary.md` and `trivy-image.json` archived |

### Build #4: dependency gate test

The dependency gate was exercised with a known vulnerable dependency, `flask==3.0.3` (PYSEC-2026-2151), intentionally used in a controlled test. A CVE here is a known software vulnerability, not malware. The flow is in section 9.

### Trend CSV repair (2026-10-16)

`security_summary.py` counted every finding as UNKNOWN because `severity_counts()` read the key `Severity` while the parsers stored `severity`. The trend rows for builds 7, 8, 9 and `nightly-1` therefore had zero severity counts with correct totals. After the one-line fix (commit `8910d6b`), those four rows were regenerated from the archived reports in Jenkins and written back in place. Timestamps, build numbers, URLs, totals and fixable counts were unchanged. The original file was kept at `/var/jenkins_home/security-trends.csv.bak-2026-10-16` inside the Jenkins container.

Corrected severity values: builds 7 and 8 are CRITICAL 2, HIGH 53, MEDIUM 120, LOW 108; build 9 and `nightly-1` are CRITICAL 2, HIGH 61, MEDIUM 112, LOW 108. Config LOW is 3 for builds 7, 8 and 9.

