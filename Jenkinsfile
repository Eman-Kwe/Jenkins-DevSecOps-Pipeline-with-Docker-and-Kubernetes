// Jenkins Declarative Pipeline — DevSecOps demo
// Every security stage follows the same pattern:
//   1. Run the scanner and write a JSON report  (|| true — never fails the build)
//   2. Run the gate command that enforces the rule and DOES fail the build
// This means a blocked build still has a report explaining why it was blocked.

pipeline {

    // Run everything on the Jenkins controller (fine for a lab; see Lab Shortcuts in README)
    agent any

    // Global environment variables available in every stage
    environment {
        // The image name. The tag is the Jenkins build number so every build
        // produces a uniquely named image — no 'latest', ever.
        IMAGE_NAME = "devsecops-app"
        IMAGE_TAG  = "${env.BUILD_NUMBER}"

        // Full image reference used in docker build, trivy scan, and kind load
        IMAGE_REF  = "${IMAGE_NAME}:${IMAGE_TAG}"

        // Path where all scanner JSON reports are written.
        // The post block archives everything under reports/ as build artifacts.
        REPORTS_DIR = "reports"
    }

    options {
        // Print a timestamp before every line in the build log.
        // Makes it easy to see how long each stage took.
        timestamps()

        // Discard old builds — keep logs and artifacts for the last 10 builds only.
        // Prevents the Jenkins volume from filling up over time.
        buildDiscarder(logRotator(numToKeepStr: '10'))
    }

    stages {

        // ------------------------------------------------------------------ //
        // STAGE 1 — Secrets scan
        // Question: Did anyone accidentally commit a credential?
        // Tool: Trivy filesystem scan with the secret scanner
        // Gate: Any secret found → fail immediately, nothing deploys
        // ------------------------------------------------------------------ //
        stage('Secrets scan') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Scan the entire repository for secrets (API keys, tokens, passwords).
                    # --exit-code 0 here so the build continues even if secrets are found —
                    # we want the JSON report written before we gate below.
                    trivy fs . \
                        --scanners secret \
                        --format json \
                        --output ${REPORTS_DIR}/trivy-secrets.json \
                        --exit-code 0 \
                        --quiet

                    # Gate: re-run with --exit-code 1 so the build fails if any secret is found.
                    # This second run is fast because it uses the same cached database.
                    trivy fs . \
                        --scanners secret \
                        --exit-code 1 \
                        --quiet
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 2 — Unit tests
        // Question: Does the application code still work correctly?
        // Tool: pytest
        // Gate: Any test failure → fail the build
        // ------------------------------------------------------------------ //
        stage('Unit tests') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Create a fresh virtual environment for the tests.
                    # Using a venv isolates test dependencies from the system Python.
                    python3 -m venv .venv-test
                    . .venv-test/bin/activate

                    # Install the app's dependencies plus pytest
                    pip install --quiet -r app/requirements.txt pytest

                    # Run pytest and write results in JUnit XML format.
                    # Jenkins reads this XML and shows pass/fail counts in the UI.
                    # --tb=short shows a short traceback on failure instead of the full one.
                    pytest app/tests \
                        --junit-xml=${REPORTS_DIR}/pytest-results.xml \
                        --tb=short

                    deactivate
                """
            }
            post {
                always {
                    // Publish JUnit results to the Jenkins build page regardless of pass/fail
                    junit "${REPORTS_DIR}/pytest-results.xml"
                }
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 3 — SAST (Static Application Security Testing)
        // Question: Does our Python source code contain dangerous patterns?
        // Tool: Semgrep with the p/python ruleset
        // Gate: Any ERROR-level finding → fail the build
        // ------------------------------------------------------------------ //
        stage('SAST') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Scan app/ with the p/python ruleset.
                    # --error makes semgrep exit non-zero on ERROR-level findings.
                    # --json writes machine-readable output for the summary script.
                    # || true so the JSON is written even when semgrep finds something —
                    # the gate below enforces the rule.
                    semgrep scan \
                        --config p/python \
                        --json \
                        --output ${REPORTS_DIR}/semgrep.json \
                        app/ || true

                    # Gate: fail the build if semgrep found any ERROR-level findings.
                    semgrep scan \
                        --config p/python \
                        --error \
                        app/
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 4 — Dependency scan (SCA — Software Composition Analysis)
        // Question: Do our Python libraries have known CVEs?
        // Tool: pip-audit
        // Gate: Any known vulnerability → fail the build
        // Note: This runs BEFORE the image is built — cheap to catch early.
        // ------------------------------------------------------------------ //
        stage('Dependency scan (SCA)') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Audit requirements.txt and all transitive dependencies.
                    # --format json writes machine-readable output.
                    # || true so the JSON is always written before the gate runs.
                    pip-audit \
                        -r app/requirements.txt \
                        --format json \
                        --output ${REPORTS_DIR}/pip-audit.json || true

                    # Gate: re-run without output redirect so pip-audit exits non-zero
                    # and prints the CVE details to the build log if anything is found.
                    pip-audit -r app/requirements.txt
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 5 — Config scan
        // Question: Are the Dockerfile and Kubernetes manifests insecure?
        // Tool: Trivy config scan
        // Gate: Any HIGH or CRITICAL misconfiguration → fail the build
        // Note: Runs BEFORE building the image — no point building an insecure image.
        // ------------------------------------------------------------------ //
        stage('Config scan') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Scan the Dockerfile and all k8s/ manifests for misconfigurations.
                    # --exit-code 0 so JSON is written regardless of findings.
                    trivy config . \
                        --format json \
                        --output ${REPORTS_DIR}/trivy-config.json \
                        --exit-code 0 \
                        --quiet

                    # Gate: fail on HIGH or CRITICAL misconfigurations only.
                    # MEDIUM and LOW are reported but don't block a release.
                    trivy config . \
                        --severity HIGH,CRITICAL \
                        --exit-code 1 \
                        --quiet
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 6 — Build image
        // Action: Build the Docker image from app/Dockerfile
        // --pull ensures we always use the newest patch of the base image,
        // so the next stage scans the most up-to-date version.
        // ------------------------------------------------------------------ //
        stage('Build image') {
            steps {
                sh """
                    # Build the app image. The tag is the Jenkins build number.
                    # --pull fetches the latest patch of python:3.12-slim-bookworm
                    # so we don't silently ship a base image with known CVEs.
                    docker build \
                        --pull \
                        -t ${IMAGE_REF} \
                        app/
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 7 — Image scan gate
        // Question: Does the finished image carry a HIGH/CRITICAL CVE with a fix?
        // Tool: Trivy image scan
        // Gate: Any HIGH or CRITICAL CVE that has a fix available → fail the build
        // --ignore-unfixed: unfixed CVEs stay in the report but don't block —
        //   there's nothing we can do about them until upstream ships a fix.
        // ------------------------------------------------------------------ //
        stage('Image scan gate') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Full scan — write JSON report with ALL findings including unfixed.
                    # This is the evidence. --exit-code 0 so it always writes.
                    trivy image \
                        --format json \
                        --output ${REPORTS_DIR}/trivy-image.json \
                        --exit-code 0 \
                        --quiet \
                        ${IMAGE_REF}

                    # Gate: fail only on HIGH/CRITICAL CVEs that HAVE a fix available.
                    # --ignore-unfixed skips CVEs where no patched version exists yet.
                    trivy image \
                        --severity HIGH,CRITICAL \
                        --ignore-unfixed \
                        --exit-code 1 \
                        --quiet \
                        ${IMAGE_REF}
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 8 — SBOM (Software Bill of Materials)
        // Action: Generate a CycloneDX inventory of every package in the image.
        // This stage NEVER fails the build — it only produces evidence.
        // Use case: when a new CVE is announced, the SBOM tells you in seconds
        //           whether the affected package is inside your image.
        // ------------------------------------------------------------------ //
        stage('SBOM') {
            steps {
                sh """
                    mkdir -p ${REPORTS_DIR}

                    # Generate a CycloneDX SBOM listing every OS and Python package
                    # in the image. CycloneDX is a standard machine-readable format.
                    trivy image \
                        --format cyclonedx \
                        --output ${REPORTS_DIR}/sbom.cdx.json \
                        --quiet \
                        ${IMAGE_REF}
                """
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 9 — Deploy to dev + smoke test
        // Action: Load the image into kind, apply the manifests to the dev namespace,
        //         wait for the rollout, then curl /health from a temporary pod.
        // Gate: Rollout failure or /health not responding → fail the build
        // ------------------------------------------------------------------ //
        stage('Deploy to dev') {
            steps {
                // withCredentials makes the kubeconfig file available as $KUBECONFIG
                // inside this block. Jenkins decrypts it from the credential store —
                // it never touches the filesystem as a readable file outside this block.
                withCredentials([file(credentialsId: 'kind-kubeconfig', variable: 'KUBECONFIG')]) {
                    sh """
                        # Load the image into the kind cluster node.
                        # 'kind load docker-image' fails from inside a Jenkins container
                        # because kind's snapshotter detection doesn't work in nested
                        # Docker environments (confirmed via investigation).
                        #
                        # Proven working alternative:
                        #   docker save  — exports the image as a raw tar stream
                        #   docker exec | ctr import — pipes it directly into the kind
                        #                              node's containerd daemon
                        #
                        # -n k8s.io is REQUIRED — Kubernetes only sees images in the
                        # k8s.io containerd namespace. Without it the image imports but
                        # pods get ErrImageNeverPull or ImagePullBackOff.
                        docker save ${IMAGE_REF} | docker exec -i devsecops-control-plane \
                            ctr -n k8s.io images import --all-platforms -

                        # Replace the BUILD_TAG placeholder in the deployment manifest
                        # with the actual build number, then apply it to the dev namespace.
                        # sed -e creates a modified version in memory without changing the file.
                        sed -e 's/BUILD_TAG/${IMAGE_TAG}/g' k8s/deployment.yaml \
                            | kubectl apply -n dev -f -

                        # Apply the service manifest (no placeholder needed here)
                        kubectl apply -n dev -f k8s/service.yaml

                        # Wait up to 120 seconds for all pods to be running and ready.
                        # This fails the build if the rollout doesn't complete in time.
                        kubectl rollout status deployment/devsecops-app \
                            -n dev \
                            --timeout=120s

                        # Smoke test: create/wait/logs/delete pattern.
                        # --rm is not supported for non-attached pods in CI (Jenkins
                        # does not keep stdin open, so --rm with --restart=Never errors).
                        # Pattern:
                        #   1. create the pod — curl hits /health, -sf fails on non-200
                        #   2. wait for Succeeded — fails the build if pod Failed or times out
                        #   3. log the output  — shows the /health response in the build log
                        #   4. delete the pod  — always clean up
                        kubectl run smoke-test \
                            --image=curlimages/curl:8.5.0 \
                            --restart=Never \
                            -n dev \
                            -- curl -sf http://devsecops-app/health

                        kubectl wait pod/smoke-test \
                            -n dev \
                            --for=jsonpath='{.status.phase}'=Succeeded \
                            --timeout=30s

                        kubectl logs smoke-test -n dev

                        kubectl delete pod smoke-test -n dev
                    """
                }
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 10 — Approve prod
        // Action: Pause and wait for a human to approve the promotion to prod.
        // This is continuous DELIVERY, not continuous DEPLOYMENT —
        // a person decides when prod gets updated.
        // Timeout: 15 minutes. If nobody approves, the build times out and
        // is marked ABORTED (not FAILED — the code was fine, nobody approved).
        // ------------------------------------------------------------------ //
        stage('Approve prod') {
            steps {
                timeout(time: 15, unit: 'MINUTES') {
                    // Pauses the build and shows an Approve/Abort button in the Jenkins UI.
                    // The build URL is printed to make it easy to find in an email or chat.
                    input message: "Deploy build #${env.BUILD_NUMBER} to prod?",
                          ok: 'Approve'
                }
            }
        }

        // ------------------------------------------------------------------ //
        // STAGE 11 — Deploy to prod
        // Action: Apply the same image (same build number) to the prod namespace.
        // The image was already scanned and smoke-tested in dev — we deploy the
        // exact same artifact, not a rebuild.
        // ------------------------------------------------------------------ //
        stage('Deploy to prod') {
            steps {
                withCredentials([file(credentialsId: 'kind-kubeconfig', variable: 'KUBECONFIG')]) {
                    sh """
                        # Same process as dev — replace the placeholder and apply.
                        # The image is already in kind from the dev deploy stage.
                        sed -e 's/BUILD_TAG/${IMAGE_TAG}/g' k8s/deployment.yaml \
                            | kubectl apply -n prod -f -

                        kubectl apply -n prod -f k8s/service.yaml

                        # Wait for prod rollout to complete before marking the build green.
                        kubectl rollout status deployment/devsecops-app \
                            -n prod \
                            --timeout=120s
                    """
                }
            }
        }

    } // end stages

    // ---------------------------------------------------------------------- //
    // POST — runs after every build, whether it passed or failed
    // This is where we generate the security summary and archive all reports.
    // A failed build still needs its report — that's how you know why it failed.
    // ---------------------------------------------------------------------- //
    post {
        always {
            sh """
                mkdir -p ${REPORTS_DIR}

                # Run the summary script to produce security-summary.md and
                # append one row to the trend CSV in /var/jenkins_home/.
                # The script never exits non-zero so it can't fail the build here.
                python3 scripts/security_summary.py \
                    --build-number ${env.BUILD_NUMBER} \
                    --build-url    ${env.BUILD_URL} \
                    --reports-dir  ${REPORTS_DIR} || true
            """

            // Archive everything in reports/ as downloadable build artifacts.
            // These are accessible from the build page in Jenkins.
            archiveArtifacts artifacts: "${REPORTS_DIR}/**",
                             allowEmptyArchive: true

            // Clean the workspace after the build to free disk space.
            cleanWs()
        }
    }

}
