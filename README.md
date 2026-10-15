# Jenkins DevSecOps Pipeline with Docker and Kubernetes

**An end-to-end CI/CD and DevSecOps lab** — automated security scanning, containerized deployment, Kubernetes orchestration, and a controlled production promotion gate, all running on a single local machine.

**Author:** Manuel Yannick Armah
**Environment:** WSL2 on Windows, Docker Desktop, Kind, Jenkins

---

## Status

| Area | State |
|------|-------|
| Core pipeline (scan → build → dev → approval → prod) | **Complete** — Build #8 deployed successfully to prod |
| Security reporting (`security_summary.py`, trend CSV, archived reports) | **Complete** |
| Nightly rescan of the production image | **Written, not yet run or verified** — `jenkins/Jenkinsfile.rescan` exists; it is **Planned / Future Work** until it has run successfully |
| Break-and-fix tests for every gate | **Planned / Future Work** — not completed; only the dependency-scan gate has been observed failing a real build (Build #4) |
| Screenshots | **Pending** — checklist in [NOTES.md](NOTES.md) |
| Video walkthrough | **Pending** |

---

## Video Walkthrough

Not recorded yet. A walkthrough link will be added here once it exists.

---

## Project Overview

### What this project does in plain English

This project takes code from a GitHub repository and deploys it to a Kubernetes cluster — but only after every automated security check passes.

Think of it as an inspection line in a factory. Every product passes through checkpoints. If one checkpoint fails, the line stops and nothing ships until the problem is fixed.

The product here is a small Python web application. The inspection line is Jenkins. The destination is a Kubernetes cluster running locally with Kind.

### Why it matters

Security is often a final manual review, after vulnerable libraries and insecure configurations are already embedded. Fixing a vulnerable dependency before deployment is a one-line change to a requirements file. Fixing it after deployment is an incident.

DevSecOps builds security into every stage instead of bolting it on at the end. This pipeline demonstrates that with automated gates that stop a build when a check fails.

### What gets built

| Output | How |
|--------|-----|
| Automated CI/CD | Jenkins declarative pipeline built from GitHub |
| Unit tests | pytest, published to Jenkins as JUnit results |
| Secret detection | Trivy filesystem scan |
| SAST | Semgrep with the `p/python` ruleset |
| Dependency scanning | pip-audit on pinned `requirements.txt` |
| Config scanning | Trivy config scan of Dockerfiles and Kubernetes manifests |
| Image scanning | Trivy image scan — HIGH/CRITICAL with a fix available fails the build |
| SBOM | CycloneDX inventory of the image |
| Container image | Multi-stage Docker build, non-root user UID 10001 |
| Kubernetes deployment | 2 replicas, readiness/liveness probes, hardened pod spec |
| Dev/prod separation | Separate namespaces in one Kind cluster |
| Smoke test | Temporary curl pod checks `/health` after the dev rollout |
| Production approval | Human approval with a 15-minute timeout |
| Security reporting | Markdown summary and trend CSV per build |

### Skills demonstrated

- Writing a multi-stage Jenkins declarative pipeline with fail-fast ordering
- Integrating secret, SAST, SCA, config, image, and SBOM tooling
- Building a hardened container image and Kubernetes pod spec
- Diagnosing nested-container problems (Jenkins in Docker, Kind in Docker, containerd)
- Making a CI step work non-interactively (smoke test)
- Debugging a parser against a changed tool output format
- Documenting lab shortcuts and their production alternatives

---

## Project Structure

```text
jenkins-devsecops-pipeline/
├── README.md                    ← project story, architecture, results
├── NOTES.md                     ← deep engineering notes and troubleshooting
├── Jenkinsfile                  ← the pipeline (11 stages + post block)
├── .trivyignore                 ← accepted-risk register (starts empty)
├── .gitignore
├── LICENSE
│
├── app/
│   ├── app.py                   ← Flask app: /, /health, /version
│   ├── requirements.txt         ← pinned dependencies (flask, gunicorn)
│   ├── Dockerfile               ← multi-stage build, non-root UID 10001
│   ├── .dockerignore
│   └── tests/test_app.py        ← 2 pytest tests
│
├── jenkins/
│   ├── Dockerfile               ← Jenkins 2.504.3 + Trivy + Semgrep + pip-audit + kubectl
│   └── Jenkinsfile.rescan       ← nightly rescan — written, not yet run or verified
│
├── k8s/
│   ├── namespaces.yaml          ← dev and prod
│   ├── deployment.yaml          ← 2 replicas, hardened pod spec, BUILD_TAG placeholder
│   └── service.yaml             ← ClusterIP, port 80 → 8080
│
├── scripts/
│   └── security_summary.py      ← scanner JSON → security-summary.md + trend CSV
│
└── images/                      ← screenshots (empty — pending)
```

---

## Architecture Diagram

```
Developer pushes to GitHub
          │
          ▼
┌─────────────────────────────────────────────────────┐
│                  JENKINS CONTAINER                   │
│                                                     │
│  1.  Checkout from GitHub                           │
│  2.  Trivy      → secrets scan          GATE ✗      │
│  3.  pytest     → unit tests            GATE ✗      │
│  4.  Semgrep    → SAST                  GATE ✗      │
│  5.  pip-audit  → dependency scan       GATE ✗      │
│  6.  Trivy      → config scan           GATE ✗      │
│  7.  Docker     → build image                       │
│  8.  Trivy      → image scan            GATE ✗      │
│  9.  Trivy      → SBOM (evidence, no gate)         │
│  10. kubectl    → deploy to dev         GATE ✗      │
│  11. curl pod   → smoke test            GATE ✗      │
│  12. Human      → approve prod          GATE ✗      │
│  13. kubectl    → deploy to prod        GATE ✗      │
│  14. Python     → security summary                  │
└─────────────────────────────────────────────────────┘
          │                          │
          │  docker save | ctr       │  kubectl apply
          ▼                          ▼
┌──────────────────┐       ┌──────────────────────┐
│  KIND CLUSTER    │       │    KIND CLUSTER       │
│  dev namespace   │       │    prod namespace     │
│  2 × replicas    │       │    2 × replicas       │
│  /health ✓       │       │    /health ✓          │
└──────────────────┘       └──────────────────────┘
```

Jenkins runs as a Docker container and uses the host Docker socket. The Kind node (`devsecops-control-plane`) is another Docker container with containerd inside. Images are built by Docker and imported straight into containerd — there is no registry in this lab.

---

## How It Works

1. A push lands in GitHub; Jenkins builds from the active project branch in GitHub.
2. Cheap checks run first (secrets, tests, SAST, dependencies, config) so failures are fast.
3. Only if those pass is the Docker image built, then scanned.
4. The image is imported into the Kind node's containerd and deployed to `dev`.
5. A smoke test proves the app answers on `/health` through the Service.
6. A person approves; the same image and build number are deployed to `prod`.
7. A post block writes the security summary and archives all reports, pass or fail.

### Pipeline stages at a glance

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

Command-level detail for each stage is in [NOTES.md](NOTES.md).

---

## Key Terms

| Term | Meaning |
|------|---------|
| **CI/CD** | Automated build, test, and delivery of code |
| **DevSecOps** | Security checks built into every pipeline stage |
| **SAST** | Static analysis of source code without running it |
| **SCA** | Checking third-party dependencies for known CVEs |
| **CVE** | A publicly catalogued vulnerability |
| **SBOM** | Inventory of every package inside an artifact |
| **Gate** | A check whose failure stops the pipeline |
| **Kind** | Kubernetes running as Docker containers |
| **containerd** | The container runtime inside the Kind node |
| **Namespace (Kubernetes)** | Logical separation inside a cluster (`dev`, `prod`) |
| **Namespace (containerd)** | Image isolation inside containerd; Kubernetes reads `k8s.io` |
| **Continuous delivery** | Every passing build is deployable; a human decides when |
| **Smoke test** | A minimal post-deploy check that the app really responds |

---

## Prerequisites

| Requirement | Version used |
|-------------|-------------|
| WSL2 with Ubuntu | 24.04 |
| Docker Desktop | 29.7.2 |
| kind | v0.27.0 |
| kubectl | v1.33.12 |
| Python 3 | 3.12.3 |
| Git | any |
| Jenkins image | `jenkins/jenkins:2.504.3-lts-jdk17` base |
| Trivy (in Jenkins image) | v0.75.0 |

---

## Naming Conventions

| Item | Name |
|------|------|
| Kind cluster | `devsecops` |
| Kind node container | `devsecops-control-plane` |
| Kubernetes namespaces | `dev`, `prod` |
| Application image | `devsecops-app:<Jenkins build number>` (no `latest`) |
| Jenkins image | `jenkins-devsecops:1.0` |
| Jenkins container | `jenkins` |
| Jenkins kubeconfig credential ID | `kind-kubeconfig` |
| Pipeline job | `devsecops-pipeline` |
| Deployment / Service | `devsecops-app` |
| Report directory | `reports/` |

---

## Project Steps

High-level path (full commands, flags, expected output, and verification are in [NOTES.md](NOTES.md)):

1. Clone the repository.
2. Build the custom Jenkins image (`jenkins/Dockerfile`).
3. Create the `devsecops` Kind cluster and apply `k8s/namespaces.yaml`.
4. Start Jenkins with a persistent volume, the Docker socket, and the `kind` network.
5. Complete Jenkins first-time setup.
6. Add the internal kubeconfig as the `kind-kubeconfig` Secret file credential.
7. Create a Pipeline-from-SCM job that reads `Jenkinsfile`.
8. Run the build and approve prod when prompted.
9. Verify: pods, `/version`, non-root UID, read-only filesystem.

---

## Results

**Build #8 — `Finished: SUCCESS`**

| Stage | Result | Observed |
|-------|--------|----------|
| Secrets scan | Pass | 0 secrets |
| Unit tests | Pass | 2/2 |
| SAST | Pass | 0 findings (151 rules, `app.py`) |
| Dependency scan | Pass | No known vulnerabilities (flask 3.1.3) |
| Config scan | Pass | 0 misconfigurations across Dockerfiles and manifests |
| Build image | Pass | `devsecops-app:8` on `python:3.12-slim-bookworm` |
| Image scan | Pass | 0 fixable HIGH/CRITICAL CVEs |
| SBOM | Pass | `sbom.cdx.json` generated |
| Deploy to dev | Pass | 2 replicas rolled out |
| Smoke test | Pass | `{"status":"ok"}` from `/health` |
| Approve prod | Pass | Manually approved |
| Deploy to prod | Pass | 2 replicas rolled out |
| Security summary | Pass | `security-summary.md` written, trend row appended |

**Failures observed along the way (real builds):**

| Build | Stage | What happened | Outcome |
|-------|-------|---------------|---------|
| #4 | Dependency scan | `flask==3.0.3` → `PYSEC-2026-2151` | Upgraded to `3.1.3`; gate worked as designed |
| #5, #6 | Deploy to dev | `kind load` → `failed to detect containerd snapshotter` | Replaced with `docker save \| ctr -n k8s.io images import` |
| — | Smoke test | `--rm should only be used for attached containers` | Replaced with create/wait/logs/delete |
| — | Post block | `security_summary.py` crashed on pip-audit's dict output | Parser now handles both formats; build was not affected |

**Evidence still to capture:** screenshots (Stage View, approval prompt, security summary, Trivy image scan, pods in dev and prod, `/version`). The checklist is in [NOTES.md](NOTES.md).

---

## Security Decisions

- **Order: cheapest check first.** Secrets and tests run before the image build, so failures there cost little; the image build only happens after source-level checks pass.
- **Two scanners for dependencies.** pip-audit covers Python packages; Trivy image scan covers OS packages pip-audit never sees.
- **Pinned versions.** `requirements.txt` is pinned to exact versions so pip-audit can look up CVEs reliably. Image tags are build numbers, never `latest`.
- **`--ignore-unfixed`.** Only findings with an available fix block the build; unfixed ones are still reported in `trivy-image.json`.
- **Non-root, minimal image.** Multi-stage build, UID 10001, no shell, no home directory, gunicorn instead of the Flask dev server.
- **Hardened pod spec.** `runAsNonRoot`, `readOnlyRootFilesystem`, `allowPrivilegeEscalation: false`, drop ALL capabilities, `seccompProfile: RuntimeDefault`, no service account token, and CPU/memory requests and limits (50m/64Mi requested, 250m/128Mi limit).
- **Build retention.** Jenkins keeps the last 10 builds and their archived reports.
- **Human approval for prod.** Continuous delivery with a 15-minute timeout; a timeout is ABORTED, not FAILED.
- **Reports on every build.** A blocked build still archives its scanner output so the block can be explained.
- **Empty `.trivyignore`.** Accepted risks would need a CVE ID, expiry, reason, approver, and ticket.

---

## Lab Shortcuts

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

Fuller tradeoff discussion is in [NOTES.md](NOTES.md).

---

## Troubleshooting / Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `failed to detect containerd snapshotter` | `kind load` does not work from inside the Jenkins container | `docker save <image> \| docker exec -i devsecops-control-plane ctr -n k8s.io images import --all-platforms -` |
| `ImagePullBackOff` / `ErrImageNeverPull` | Image imported without `-n k8s.io`, so Kubernetes cannot see it | Import into the `k8s.io` containerd namespace |
| `--rm should only be used for attached containers` | Jenkins shell steps have no attached stdin | Create, wait, logs, delete pattern |
| pip-audit stage red | Pinned package has a known CVE | Upgrade the pinned version |
| `kubectl` connection refused from Jenkins | Kubeconfig points at `127.0.0.1` | Use `kind get kubeconfig --internal` |
| `[summary] ERROR: 'str' object has no attribute 'get'` | pip-audit output is a dict with a `dependencies` key | Parser handles dict and legacy list |

Full stories, root-cause analysis, and diagnostic commands: [NOTES.md](NOTES.md).

---

## Key Takeaways

- **Troubleshoot layer by layer.** The image-loading failure looked like a Kubernetes problem; testing the Docker socket, node exec, containerd, and namespace in turn located it.
- **Separate build problems from deployment problems.** The smoke test failure happened after a successful rollout; checking pod state first narrows the cause.
- **A gate you have seen fail is a gate you can explain.** Build #4 showed the dependency gate working; the remaining gates have not yet been deliberately exercised.
- **Pin versions and read changelogs.** A nonexistent Trivy version and a changed pip-audit JSON format both caused misleading failures.
- **Know the tradeoff behind every shortcut.** The lab is not production-ready, and the README says where it differs.

---

## Honest Scope

**What this project demonstrates:** a working scan-build-deploy-approve pipeline on a single machine, with scanners, gates, a hardened image and pod spec, a smoke test, and per-build reporting. Build #8 completed end to end.

**What it does not demonstrate:**
- A nightly rescan of the production image (**planned, not completed**)
- Deliberate break-and-fix tests for every gate (**planned, not completed**)
- Multi-node, multi-cluster, or cloud deployment
- A container registry, image signing, or policy enforcement
- Production-grade secrets management or build isolation
- Monitoring or alerting

---

## What I'd Do Next

**Planned / Future Work — not completed:**

1. Nightly rescan of the production image against current CVE data
2. Break-and-fix tests: introduce a fake secret, a vulnerable dependency, and a misconfigured manifest to prove each gate independently

**Further improvements:**

| Improvement | Adds | Priority |
|-------------|------|----------|
| Container registry | Pull-based deployment, multi-node support | High |
| Managed Kubernetes | Production-grade cluster | High |
| Kaniko or Buildah | Removes Docker socket dependency | High |
| Workload identity | No long-lived kubeconfig | High |
| Argo CD or Flux | GitOps audit trail and drift detection | Medium |
| Secrets manager | Rotation and audit | Medium |
| Cosign image signing | Proof of build origin | Medium |
| OPA / Kyverno | Admission-time policy | Medium |
| OWASP ZAP | Dynamic testing of the dev deployment | Medium |
| Prometheus + Grafana | Metrics and alerting | Medium |
| Helm, Terraform | Templating, infrastructure as code | Low |

---

## References

- Jenkins documentation — https://www.jenkins.io/doc/
- Trivy — https://trivy.dev/
- Semgrep — https://semgrep.dev/docs/
- pip-audit — https://github.com/pypa/pip-audit
- kind — https://kind.sigs.k8s.io/
- Kubernetes documentation — https://kubernetes.io/docs/
- containerd — https://containerd.io/
- CycloneDX — https://cyclonedx.org/
- Deep notes for this project — [NOTES.md](NOTES.md)
