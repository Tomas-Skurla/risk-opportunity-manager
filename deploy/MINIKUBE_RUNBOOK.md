# RiskApp local Kubernetes runbook

This lab runs on an Ubuntu 26.04 VM in Hyper-V with rootless Docker and a Minikube cluster using the Docker driver and containerd. Run the commands inside Ubuntu, from `~/Desktop/src/risk-opportunity-manager`. The API stays inside the cluster; Ubuntu reaches it through a temporary port-forward bound to `127.0.0.1`.

## What is deployed

| File | Resource | Purpose |
| --- | --- | --- |
| `deploy/k8s/configmap.yaml` | ConfigMap `riskapp-config` | Non-secret settings, including the SQLite URL |
| `deploy/k8s/pvc.yaml` | PVC `riskapp-data` | 1 GiB of persistent storage |
| `deploy/k8s/deployment.yaml` | Deployment `riskapp-api` | One API Pod with the PVC at `/data` and a `/health` readiness probe |
| `deploy/k8s/services.yaml` | Service `riskapp-api` | Cluster-internal address on port 8000 |
| `deploy/swagger/` | Deployment and Service `riskapp-swagger`, ConfigMap `riskapp-swagger-env` | Optional Swagger UI that works offline, see step 6 |

The Deployment also reads a Secret `riskapp-secrets`, created in step 2. It uses the image `riskapp-api:lab-1` with pull policy `Never`, so that image must be loaded into Minikube first. Nothing is pushed to a registry.

## 1. Build and load the image

```bash
docker context show                   # expected: rootless
docker compose build api              # builds riskapp-api:local
docker tag riskapp-api:local riskapp-api:lab-1
minikube start --driver=docker --container-runtime=containerd
minikube -p minikube image load riskapp-api:lab-1
minikube -p minikube image ls | grep riskapp-api
kubectl --context minikube get nodes  # expected: Ready
```

The first build and cluster start may need internet access; once everything is cached, the lab works offline.

## 2. Create the namespace and Secret

Create the namespace once:

```bash
kubectl --context minikube create namespace riskapp
```

Generate `.env.k8s.local` **only if it does not exist yet**. It holds the signing keys and the initial admin login, and Git ignores it (`.env.*`):

```bash
umask 077
cat > .env.k8s.local <<EOF
SECRET_KEY=$(openssl rand -hex 32)
TOKEN_HASH_KEY=$(openssl rand -hex 32)
INITIAL_SUPERUSER_EMAIL=admin@example.com
INITIAL_SUPERUSER_PASSWORD=Lab1!$(openssl rand -hex 16)
EOF
git check-ignore -v .env.k8s.local
```

Do not regenerate it while keeping the database: new keys invalidate existing tokens, and the bootstrap password is only used when the admin account is first created. Create the Secret once:

```bash
kubectl --context minikube -n riskapp create secret generic riskapp-secrets \
  --from-env-file=.env.k8s.local
kubectl --context minikube -n riskapp describe secret riskapp-secrets
```

`describe` shows key names and sizes, not values.

## 3. Deploy

```bash
kubectl --context minikube apply --dry-run=server -f deploy/k8s/
kubectl --context minikube apply -f deploy/k8s/
kubectl --context minikube -n riskapp get pods,pvc,svc
```

The dry run validates the manifests, but not whether the Pod can start or the Secret exists. Expect a Pod at `READY 1/1`, a `Bound` PVC and a `ClusterIP` Service on 8000/TCP. If the Pod gets stuck:


```bash
kubectl --context minikube -n riskapp describe pods -l app=riskapp-api
kubectl --context minikube -n riskapp logs deployment/riskapp-api
```

## 4. Reach the API

In terminal A, leave the port-forward running:

```bash
kubectl --context minikube -n riskapp port-forward \
  --address 127.0.0.1 service/riskapp-api 8000:8000
```

In terminal B, `curl --fail --show-error http://127.0.0.1:8000/health` returns `{"status":"ok","db":"ok"}`. Use `http`: the API does not terminate TLS.

## 5. Show that the data survives a Pod replacement

In terminal B, log in and create a project without printing the credentials:

```bash
. ./.env.k8s.local
RISKAPP_TOKEN="$(curl --fail --silent --show-error \
  http://127.0.0.1:8000/login \
  --data-urlencode "username=$INITIAL_SUPERUSER_EMAIL" \
  --data-urlencode "password=$INITIAL_SUPERUSER_PASSWORD" |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')"
RISKAPP_PROJECT_ID="$(curl --fail --silent --show-error \
  http://127.0.0.1:8000/projects \
  -H "Authorization: Bearer $RISKAPP_TOKEN" \
  --json '{"name":"Kubernetes PVC demo","description":"Persistence check"}' |
  python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
test -n "$RISKAPP_PROJECT_ID" && echo 'Project created'
```

Replace the Pod and wait for the new one; the PVC stays:

```bash
kubectl --context minikube -n riskapp rollout restart deployment/riskapp-api
kubectl --context minikube -n riskapp rollout status deployment/riskapp-api --timeout=180s
```

The port-forward exits with the old Pod, so restart it in terminal A, then read the project in terminal B:

```bash
curl --fail --show-error "http://127.0.0.1:8000/projects/$RISKAPP_PROJECT_ID" \
  -H "Authorization: Bearer $RISKAPP_TOKEN"
```

The same ID and name show that the SQLite data survived on the PVC. A `401` means the access token expired; log in again and repeat the request.

## 6. Swagger UI offline

FastAPI's `/docs` page loads Swagger UI from a CDN, so it stays blank while the VM is offline. `deploy/swagger/` runs the Swagger UI image in the cluster instead, pointed at `http://127.0.0.1:8000/openapi.json`; the API's ConfigMap already allows its origin, `http://127.0.0.1:8081`. Its pull policy is also `Never`, so load the image while online:

```bash
docker pull docker.swagger.io/swaggerapi/swagger-ui:v5.32.0
minikube -p minikube image load docker.swagger.io/swaggerapi/swagger-ui:v5.32.0
kubectl --context minikube apply -f deploy/swagger/
kubectl --context minikube -n riskapp port-forward \
  --address 127.0.0.1 service/riskapp-swagger 8081:8080
```

With the API port-forward from step 4 still running, open `http://127.0.0.1:8081`.
