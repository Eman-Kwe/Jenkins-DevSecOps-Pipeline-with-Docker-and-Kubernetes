# Build Log

Every error hit during this build, what caused it, and how it was fixed.
Format: **What I saw → What caused it → How I fixed it**

---

## Environment Setup

### kind cluster named my-cluster instead of devsecops
**What I saw:** `kind get clusters` returned `my-cluster` instead of `devsecops`.  
**What caused it:** The cluster was created earlier during environment testing with the wrong name, or from a prior project. The README specifies the cluster must be named `devsecops` so Jenkins can connect to it via the kind Docker network with the correct internal address.  
**How I fixed it:** `kind delete cluster --name my-cluster` then `kind create cluster --name devsecops`.

### kubectl connection refused to 127.0.0.1:46835
**What I saw:** `kubectl get nodes` returned `connection refused`.  
**What caused it:** The `my-cluster` kind cluster had its API server port binding go stale — likely after a Docker Desktop restart. The kind containers (`my-cluster-worker`, `my-cluster-worker2`) were still running but the API server was unreachable.  
**How I fixed it:** Deleted the broken cluster and created `devsecops` fresh.

---

## Step 4 – App and Tests

*(Add notes here as you encounter issues)*

## Step 5 – Docker Image

*(Add notes here as you encounter issues)*

## Step 6 – Kubernetes Manifests

*(Add notes here as you encounter issues)*

## Step 8 – kind Cluster

*(Add notes here as you encounter issues)*

## Step 9 – Jenkins Container

*(Add notes here as you encounter issues)*

## Step 10 – Kubeconfig Credential

*(Add notes here as you encounter issues)*

## Step 11 – Jenkinsfile

*(Add notes here as you encounter issues)*

## Step 12 – First Pipeline Run

*(Add notes here as you encounter issues)*

## Step 13 – Prod Verification

*(Add notes here as you encounter issues)*

## Step 14 – Break-and-Fix Tests

*(Add notes here as you encounter issues)*

## Step 15 – Nightly Rescan

*(Add notes here as you encounter issues)*
