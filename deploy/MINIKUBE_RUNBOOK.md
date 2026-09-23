# RiskApp local Kubernetes runbook

This lab runs on an Ubuntu 26.04 VM in Hyper-V with rootless Docker and a
Minikube cluster using the Docker driver and containerd. Commands below run
**inside Ubuntu**, from `~/Desktop/src/risk-opportunity-manager`. The deployed
API stays inside the cluster, access from Ubuntu uses a temporary port-forward
bound to `127.0.0.1`.

## What is deployed

| File | Kubernetes resource | Job |
| --- | --- | --- |
| `deploy/k8s/configmap.yaml` | ConfigMap `riskapp-config` | Non-secret app settings, including the SQLite URL |
| `deploy/k8s/pvc.yaml` | PVC `riskapp-data` | Requests 1 GiB of persistent storage |
| `deploy/k8s/deployment.yaml` | Deployment `riskapp-api` | Runs one API Pod, mounts the PVC at `/data`, checks `/health` |
| `deploy/k8s/service.yaml` | Service `riskapp-api` | Stable cluster-internal address on port 8000 |

The Deployment also reads a separately created Secret named `riskapp-secrets`.
The image tag in the Deployment is `riskapp-api:lab-1`, its pull policy is
`Never`, so this exact image must be loaded into Minikube before applying the
manifests. None of these commands pushes an image to a public registry.

## 1. Build and load the image

From the repository root:

```bash
docker context show                   # expected: rootless
docker compose build api              # builds riskapp-api:local
docker tag riskapp-api:local riskapp-api:lab-1
minikube start --driver=docker --container-runtime=containerd
minikube -p minikube image load riskapp-api:lab-1
minikube -p minikube image ls | grep riskapp-api
kubectl --context minikube get nodes  # expected: Ready
```

The initial image build or cluster setup may need internet access for
uncached dependencies. After the image and Kubernetes components are cached,
the running lab and loopback access can work offline.

## 2. Create the namespace and Secret

Create the namespace once, skip this command when `riskapp` already exists:

```bash
kubectl --context minikube create namespace riskapp
```

Generate `.env.k8s.local` **only if it does not already exist**. This file
holds the signing keys and the initial admin login. Keep it in the repository
root, `.gitignore` and `.dockerignore` should exclude `.env.*`.

```bash
umask 077
cat > .env.k8s.local <<EOF
SECRET_KEY=$(openssl rand -hex 32)
TOKEN_HASH_KEY=$(openssl rand -hex 32)
INITIAL_SUPERUSER_EMAIL=admin@example.com
INITIAL_SUPERUSER_PASSWORD=Lab1!$(openssl rand -hex 16)
EOF
git check-ignore -v .env.k8s.local
ls -l .env.k8s.local
```

Do not regenerate this file while keeping the database: changed signing keys
affect existing authentication, and the bootstrap password is used only when
the admin account is first created. Create the namespaced Secret once:

```bash
kubectl --context minikube -n riskapp create secret generic riskapp-secrets \
  --from-env-file=.env.k8s.local
kubectl --context minikube -n riskapp describe secret riskapp-secrets
```

`describe` shows key names and sizes without displaying their values. The
Secret is a Kubernetes object, the `.env.k8s.local` file remains on Ubuntu.

## 3. Validate and deploy

Confirm `deploy/k8s/` contains the four YAML manifests. A server dry run
validates them without creating resources, but does not check whether a Pod
can start or whether the referenced Secret exists.

```bash
ls deploy/k8s/*.yaml
kubectl --context minikube apply --dry-run=server -f deploy/k8s/
kubectl --context minikube apply -f deploy/k8s/
kubectl --context minikube -n riskapp get pods,pvc,svc
```

Expect a Pod at `READY 1/1`, a `Bound` PVC, and a `ClusterIP` Service on
8000/TCP. To observe Pod creation, run `kubectl --context minikube -n riskapp
get pods --watch` in another terminal before applying. `kubectl rollout
status deployment/riskapp-api` is an optional **watch**, `apply` already made
Kubernetes create the Pod.

If it gets stuck, inspect the Pod and application output:

```bash
kubectl --context minikube -n riskapp describe pods -l app=riskapp-api
kubectl --context minikube -n riskapp logs deployment/riskapp-api
```

## 4. Reach the local API

In Ubuntu terminal A, leave this running:

```bash
kubectl --context minikube -n riskapp port-forward \
  --address 127.0.0.1 service/riskapp-api 8000:8000
```

In Ubuntu terminal B:

```bash
curl --fail --show-error http://127.0.0.1:8000/health
```

The observed response was `{"status":"ok","db":"ok"}`. Use `http`, not
`https`: this API does not terminate TLS on port 8000. The `ClusterIP`
Service remains inside Kubernetes, the port-forward is temporary and only
listens on Ubuntu's loopback address.

## 5. Prove the database survives Pod replacement

In terminal B, from the repository root, load the local admin credentials and
obtain an access token without printing either credential:

```bash
. ./.env.k8s.local
RISKAPP_TOKEN="$(curl --fail --silent --show-error \
  http://127.0.0.1:8000/login \
  --data-urlencode "username=$INITIAL_SUPERUSER_EMAIL" \
  --data-urlencode "password=$INITIAL_SUPERUSER_PASSWORD" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
test -n "$RISKAPP_TOKEN" && echo 'Login succeeded'
```

Create one disposable project and retain its ID in **the same terminal**:

```bash
RISKAPP_PROJECT_ID="$(curl --fail --silent --show-error \
  http://127.0.0.1:8000/projects \
  -H "Authorization: Bearer $RISKAPP_TOKEN" \
  --json '{"name":"Kubernetes PVC demo","description":"Persistence check"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
test -n "$RISKAPP_PROJECT_ID" && echo 'Project created'
```

`rollout restart` deliberately replaces the Pod, `rollout status` then waits
for its replacement to become ready. The PVC is retained:

```bash
kubectl --context minikube -n riskapp rollout restart deployment/riskapp-api
kubectl --context minikube -n riskapp rollout status \
  deployment/riskapp-api --timeout=180s
kubectl --context minikube -n riskapp get pods,pvc
```

The old port-forward can exit when its Pod disappears. Restart the command
from section 4 in terminal A, then read the project from terminal B:

```bash
curl --fail --show-error \
  "http://127.0.0.1:8000/projects/$RISKAPP_PROJECT_ID" \
  -H "Authorization: Bearer $RISKAPP_TOKEN"
```

The same project ID and name after the Pod replacement demonstrate that
SQLite data survived on the PVC. If the request returns `401`, obtain a fresh
access token and repeat the GET. This procedure was completed successfully
for the `Kubernetes PVC demo` project.

## 6. Make Swagger UI usable offline

FastAPI's default `/docs` HTML loads Swagger JavaScript and CSS from an
external CDN. When the VM is offline, Firefox can show a blank page with
`SwaggerUIBundle is not defined`, even while `/health` works. Browser cache is
not a reliable project dependency. Serve versioned Swagger assets from the
RiskApp image instead. FastAPI documents this approach in its
[self-hosted docs guide](https://fastapi.tiangolo.com/how-to/custom-docs-ui-assets/).

While online **once**, download matching files from a pinned Swagger UI
release, or download them on another machine and copy them into this folder.
Keep the upstream license and any notices when adding third-party assets to
the public repository.

```bash
mkdir -p server/riskapp_server/static
curl -fsSL \
  https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.0/swagger-ui-bundle.js \
  -o server/riskapp_server/static/swagger-ui-bundle.js
curl -fsSL \
  https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.32.0/swagger-ui.css \
  -o server/riskapp_server/static/swagger-ui.css
```

In `server/riskapp_server/main/app.py`:

1. Import `Path` from `pathlib`, `get_swagger_ui_html` and
   `get_swagger_ui_oauth2_redirect_html` from `fastapi.openapi.docs`,
   `StaticFiles` from `fastapi.staticfiles`, and `HTMLResponse` from
   `fastapi.responses`.
2. In `create_app()`, add `docs_url=None, redoc_url=None` to the existing
   `FastAPI(...)` call. This disables the default pages that request CDN
   assets.
3. After the `FastAPI(...)` call, add the following mount and handlers
   (using the existing local variable `application`):

```python
    static_dir = Path(__file__).resolve().parents[1] / "static"
    application.mount(
        "/static", StaticFiles(directory=static_dir), name="docs-static"
    )

    @application.get("/docs", include_in_schema=False)
    def local_swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=application.openapi_url,
            title=f"{application.title} - Swagger UI",
            swagger_js_url="/static/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui.css",
            swagger_favicon_url="data:,",
            oauth2_redirect_url=application.swagger_ui_oauth2_redirect_url,
            swagger_ui_parameters={"validatorUrl": None},
        )

    @application.get(
        application.swagger_ui_oauth2_redirect_url, include_in_schema=False
    )
    def local_swagger_redirect() -> HTMLResponse:
        return get_swagger_ui_oauth2_redirect_html()
```

The Dockerfile already uses `COPY server ./server`, so it includes these files
in new server images. Build and load a **new** tag, update the image in
`deploy/k8s/deployment.yaml` to `riskapp-api:lab-2`, then apply it:

```bash
docker compose build api
docker tag riskapp-api:local riskapp-api:lab-2
minikube -p minikube image load riskapp-api:lab-2
kubectl --context minikube apply -f deploy/k8s/deployment.yaml
kubectl --context minikube -n riskapp rollout status \
  deployment/riskapp-api --timeout=180s
```

Restart the port-forward if it exited. Confirm `curl -I` gets HTTP 200 for
both `/static/swagger-ui-bundle.js` and `/static/swagger-ui.css`, then reload
`http://127.0.0.1:8000/docs` in Firefox while the VM is offline. In the
browser Network panel, the JavaScript and CSS should load from
`127.0.0.1:8000/static/`, with no request to the CDN. This is a future change
to implement and verify, the initial `lab-1` image still uses CDN assets.
