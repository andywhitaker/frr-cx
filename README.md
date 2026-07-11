# frr-cx

FRRouting SimNode image for [Nokia Event-Driven Automation (EDA)](https://docs.eda.dev/) CX digital twin.

On boot the container discovers its CX identity, downloads FRR config files from the EDA artifact server (`eda-asvr`), then starts FRR.

## Image

```bash
docker pull ghcr.io/andywhitaker/frr-cx:10.6.1
```

| | |
|---|---|
| **Image** | `ghcr.io/andywhitaker/frr-cx:10.6.1` |
| **Base** | `quay.io/frrouting/frr:10.6.1` |
| **Registry** | GitHub Container Registry |

Use this image as the SimNode container image in your EDA NetworkTopology / SimNode definition.

## How it works

1. **Wait for datapath** — CX injects `eth1`, `eth2`, …; management stays on `eth0`.
2. **Enable IPv6** on datapath interfaces (for BGP unnumbered / NDP use cases).
3. **Resolve identity** from the pod (in order):
   - Env: `CX_NODE_NAMESPACE` + `CX_CHASSIS_NAME`
   - Kubernetes API pod labels: `cx-node-namespace`, `cx-chassis-name`
   - Pod name pattern: `cx-<namespace>--<chassis>-sim-...`
4. **Download configs** from the artifact server into `/etc/frr` (one Artifact URL per file):

   ```text
   https://eda-asvr.eda-system.svc/{namespace}/frr-cx-configs/frr-cx-{chassis}-daemons/daemons
   https://eda-asvr.eda-system.svc/{namespace}/frr-cx-configs/frr-cx-{chassis}-frr-conf/frr.conf
   https://eda-asvr.eda-system.svc/{namespace}/frr-cx-configs/frr-cx-{chassis}-vtysh-conf/vtysh.conf
   ```

5. **Start FRR** via the stock `/usr/lib/frr/docker-start`.

## Build locally

```bash
make build
# tags both:
#   ghcr.io/andywhitaker/frr-cx:10.6.1
#   frr-cx:10.6.1

# Optional: load into kind (EDA playground)
make load-kind
```

## Publish

Images are published to GHCR automatically on push to `main` via GitHub Actions.

To push from your machine (requires a token with `write:packages`):

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u andywhitaker --password-stdin
make push
```

## Kubernetes RBAC (optional)

SimNodes run as the `default` ServiceAccount in `eda-system`. To allow label discovery via the API:

```bash
kubectl apply -f k8s/pod-reader-rbac.yaml
```

Without this, identity falls back to pod-name parsing or explicit env vars.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CX_NODE_NAMESPACE` | *(from pod)* | EDA logical namespace |
| `CX_CHASSIS_NAME` | *(from pod)* | Chassis / SimNode name |
| `ASVR_BASE_URL` | `https://eda-asvr.eda-system.svc` | Artifact server base URL |
| `ASVR_REPO` | `frr-cx-configs` | Artifact repo segment |
| `ASVR_TLS_VERIFY` | `false` | Verify TLS when talking to asvr |
| `CONFIG_FETCH_RETRIES` | `30` | Download attempts per file |
| `CONFIG_FETCH_DELAY` | `2` | Seconds between retries |
| `DATAPATH_WAIT_SECONDS` | `30` | Max wait for CX interfaces |

## License

Wrapper scripts in this repository are provided as-is for lab / SimNode use.  
FRR itself is GPL-2.0-or-later (see upstream [FRRouting](https://github.com/FRRouting/frr)).
