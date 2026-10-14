# Build Log

Every error hit during this build, what caused it, and how it was fixed.
Format: **What I saw → What caused it → How I fixed it**

---

## Environment Setup

### kind cluster named my-cluster instead of devsecops
**What I saw:** `kind get clusters` returned `my-cluster` instead of `devsecops`.  
**What caused it:** The cluster was created earlier during environment testing with the wrong name.  
**How I fixed it:** `kind delete cluster --name my-cluster` then `kind create cluster --name devsecops`.

### kubectl connection refused to 127.0.0.1:46835
**What I saw:** `kubectl get nodes` returned `connection refused`.  
**What caused it:** The `my-cluster` kind cluster had its API server port binding go stale after a Docker Desktop restart. The kind containers were still running but the API server was unreachable.  
**How I fixed it:** Deleted the broken cluster and created `devsecops` fresh.

---

## Jenkins Image Build

### Trivy install script failed — exit code 1
**What I saw:** Docker build failed at the Trivy install step with exit code 1.  
**What caused it:** Two issues combined:
1. The README specified Trivy `v0.56.2` which does not exist on GitHub — the API returns `Not Found`.
2. `ARG` variables were not expanding inside piped curl commands in Docker BuildKit.  
**How I fixed it:** Replaced the install script with a direct tarball download using a hardcoded URL. Updated to `v0.75.0` which is confirmed to exist.

### Jenkins 2.462.3 plugin version mismatch
**What I saw:** After first-time plugin install, every plugin failed to load with "Jenkins 2.479+ or higher required".  
**What caused it:** The Jenkins base image in `jenkins/Dockerfile` was `2.462.3-lts-jdk17`. The current plugin versions published to the Jenkins update center now require a minimum of Jenkins 2.479+.  
**How I fixed it:** Updated the base image to `jenkins/jenkins:2.504.3-lts-jdk17` which satisfies all plugin requirements.

---

## Pipeline Failures — Lessons Learned

### Failure 1: Flask CVE caught by Dependency Scan (SCA gate)

**What I saw:** Build #4 failed at the Dependency scan stage:
```
flask 3.0.3   PYSEC-2026-2151   fix: 3.1.3
```

**What caused it:** `app/requirements.txt` pinned Flask at `3.0.3` which had a known vulnerability. pip-audit correctly identified it and the gate failed the build as designed. Nothing deployed.

**What this demonstrates:** The pipeline working correctly. A vulnerable dependency was caught before an image was built, before anything touched a cluster.

**How I fixed it:** Updated `app/requirements.txt` to `flask==3.1.3`. The next build passed the SCA gate with `No known vulnerabilities found`.

---

### Failure 2: Kind image loading — `failed to detect containerd snapshotter`

**What I saw:** Build #5 and #6 failed at the Deploy to dev stage:
```
ERROR: failed to detect containerd snapshotter
```

**Environment:**
- Jenkins runs inside a Docker container, accessing Docker via `/var/run/docker.sock`
- The kind Kubernetes control-plane (`devsecops-control-plane`) is a separate Docker container
- Jenkins could successfully run `docker` commands and `docker exec` into the kind node
- containerd and `ctr` were healthy inside the kind node

**Root cause:** `kind load docker-image` works in two steps internally:
1. Connect to Docker to get the image — this worked
2. Detect which containerd snapshotter (`overlayfs` or `fuse-overlayfs`) the kind node is using, then push the image into it — **this failed**

The snapshotter detection step makes API calls to the containerd socket from the caller's perspective. When called from inside a Jenkins container (nested Docker environment), the detection path fails even though the Docker socket is mounted and the kind node is reachable. Setting `KIND_EXPERIMENTAL_PROVIDER=docker` changes how kind connects to Docker but does not fix the snapshotter detection step — confirmed by testing.

**Troubleshooting performed:**
- Confirmed Jenkins is containerized with Docker socket mounted at `/var/run/docker.sock`
- Confirmed Jenkins can run `docker exec devsecops-control-plane hostname` successfully
- Confirmed containerd is running inside the kind node: `ctr version` returned v2.0.2
- Confirmed `ctr` is available inside the kind node
- Tested `docker save | docker exec | ctr import` directly from Jenkins — succeeded in 2.3 seconds
- Confirmed image appeared in `ctr -n k8s.io images ls` after import

**Working solution:**
```bash
docker save ${IMAGE_REF} | docker exec -i devsecops-control-plane \
    ctr -n k8s.io images import --all-platforms -
```

**Why `-n k8s.io` is required:** containerd uses namespaces to isolate images between different consumers. Kubernetes (via the CRI plugin) only reads images from the `k8s.io` namespace. If you import without specifying `-n k8s.io`, the image lands in the `default` containerd namespace and Kubernetes cannot see it — pods fail with `ErrImageNeverPull` or `ImagePullBackOff` even though the image exists in containerd. The `-n k8s.io` flag is what makes the image visible to the kubelet.

**Engineering lesson:** `kind load docker-image` is designed to be called from the host machine, not from inside a Docker container. When Jenkins runs in a container and needs to push images into a kind cluster, bypass `kind load` entirely and use `docker save | ctr import` with the correct containerd namespace.

---

### Failure 3: Smoke test — `--rm should only be used for attached containers`

**What I saw:** The Deploy to dev stage failed at the smoke test step:
```
--rm should only be used for attached containers
```

**What caused it:** The original smoke test command used `kubectl run` with `--rm`. The `--rm` flag tells kubectl to delete the pod after it exits, but it only works when the process is attached to the pod's stdin/stdout. Jenkins does not keep stdin open during a shell step — it is non-interactive. kubectl detected no attachment and refused to run.

**How I fixed it:** Replaced `--rm` with an explicit create/wait/logs/delete pattern:
```bash
# Create the pod
kubectl run smoke-test --image=curlimages/curl:8.5.0 \
    --restart=Never -n dev -- curl -sf http://devsecops-app/health

# Wait for it to complete successfully
kubectl wait pod/smoke-test -n dev \
    --for=jsonpath='{.status.phase}'=Succeeded --timeout=30s

# Print the response to the build log
kubectl logs smoke-test -n dev

# Always clean up
kubectl delete pod smoke-test -n dev
```

**Why this works in CI:** Each step is independent. `kubectl wait` blocks until the pod phase is `Succeeded` (curl exited 0, meaning `/health` returned 200) or times out (which fails the build). The pod's exit code determines whether the `Succeeded` condition is met — if curl fails, the pod phase is `Failed`, `kubectl wait` times out, and the build fails.

**Result:** `{"status":"ok"}` printed to the build log. Pod deleted. Build continued to Approve prod.

**Engineering lesson:** `kubectl run --rm` is a convenient shortcut for interactive terminal sessions. In CI, always use explicit create/wait/delete — it gives you control over each step, cleaner logs, and guaranteed cleanup even if an intermediate step fails.

---

### Non-blocking: `security_summary.py` — `'str' object has no attribute 'get'`

**What I saw:** The post-build summary script printed an error but did not fail the build (the script catches all exceptions by design):
```
[summary] ERROR: 'str' object has no attribute 'get'
```

**What caused it:** The `parse_pip_audit` function expected pip-audit's JSON output to be a bare list (`[{...}, {...}]`). pip-audit 2.7.3 changed the format to a dict with a `dependencies` key: `{"dependencies": [{...}, {...}]}`. The function was iterating over the top-level dict and calling `.get()` on the string keys instead of the package dicts inside the list.

**How I fixed it:** Updated `parse_pip_audit` to detect the format and normalise before parsing:
```python
if isinstance(data, dict):
    packages = data.get("dependencies", []) or []
else:
    packages = data or []  # legacy bare list format
```

**Engineering lesson:** Pin your tool versions AND read their changelogs when upgrading. A JSON schema change in a scanner's output format is a silent breaking change for any downstream parser. Test parsers against real tool output, not assumed formats.

---

## Final Pipeline Result — Build #8

```
Finished: SUCCESS
```

| Stage | Result | Notes |
|-------|--------|-------|
| Secrets scan | ✅ | 0 secrets |
| Unit tests | ✅ | 2/2 passed |
| SAST | ✅ | 0 findings (151 rules on app.py) |
| Dependency scan | ✅ | No known vulnerabilities (flask 3.1.3) |
| Config scan | ✅ | 0 misconfigurations across all Dockerfiles and manifests |
| Build image | ✅ | devsecops-app:8, python:3.12-slim-bookworm |
| Image scan gate | ✅ | 0 fixable HIGH/CRITICAL CVEs |
| SBOM | ✅ | sbom.cdx.json generated |
| Deploy to dev | ✅ | 2 replicas rolled out |
| Smoke test | ✅ | `{"status":"ok"}` from /health |
| Approve prod | ✅ | Approved by Eman Kwe |
| Deploy to prod | ✅ | 2 replicas rolled out |
| Security summary | ✅ | security-summary.md written, trend row appended |
