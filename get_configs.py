#!/usr/bin/env python3
"""Bootstrap FRR config files from the Nokia EDA artifact server.

Discovery flow:
  1. Identify this pod via the Kubernetes API (ServiceAccount token).
  2. Read CX labels:
       cx-node-namespace  -> EDA logical namespace (not the K8s pod namespace)
       cx-chassis-name    -> SimNode / chassis name
  3. Download FRR files from the artifact server (one Artifact URL per file):

       .../{namespace}/frr-cx-configs/frr-cx-{chassis}-daemons/daemons
       .../{namespace}/frr-cx-configs/frr-cx-{chassis}-frr-conf/frr.conf
       .../{namespace}/frr-cx-configs/frr-cx-{chassis}-vtysh-conf/vtysh.conf

Environment overrides (optional, useful for local testing):
  HOSTNAME              Pod name (set automatically by Kubernetes)
  POD_NAMESPACE         K8s namespace (defaults to SA namespace file)
  CX_NODE_NAMESPACE     Skip API discovery; use this EDA namespace
  CX_CHASSIS_NAME       Skip API discovery; use this chassis name
  ASVR_BASE_URL         Artifact server base (default: https://eda-asvr.eda-system.svc)
  ASVR_REPO             Artifact repo name (default: frr-cx-configs)
  ASVR_TLS_VERIFY       "true"/"false" (default: false; asvr uses cluster-internal TLS)
  FRR_CONFIG_DIR        Destination directory (default: /etc/frr)
  CONFIG_FETCH_RETRIES  Download attempts per file (default: 30)
  CONFIG_FETCH_DELAY    Seconds between retries (default: 2)
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

SA_TOKEN_PATH = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
SA_CA_PATH = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
SA_NS_PATH = pathlib.Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")

K8S_API = os.environ.get("KUBERNETES_SERVICE_HOST")
K8S_API_PORT = os.environ.get("KUBERNETES_SERVICE_PORT", "443")

LABEL_NAMESPACE = "cx-node-namespace"
LABEL_CHASSIS = "cx-chassis-name"

# filename -> artifact name suffix used in the asvr path segment
# URL: {base}/{ns}/{repo}/frr-cx-{chassis}-{suffix}/{filename}
CONFIG_ARTIFACTS = (
    ("daemons", "daemons"),
    ("frr.conf", "frr-conf"),
    ("vtysh.conf", "vtysh-conf"),
)

# CX pod names look like: cx-<eda-ns>--<chassis>-sim-<replicaset>-<id>
POD_NAME_RE = re.compile(
    r"^cx-(?P<ns>[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)--"
    r"(?P<chassis>[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)-sim-",
    re.IGNORECASE,
)


def log(msg: str) -> None:
    print(f"[frr-cx] {msg}", flush=True)


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def ssl_context(cafile: pathlib.Path | None = None, verify: bool = True) -> ssl.SSLContext:
    if not verify:
        ctx = ssl._create_unverified_context()
        return ctx
    if cafile and cafile.is_file():
        return ssl.create_default_context(cafile=str(cafile))
    return ssl.create_default_context()


def http_get(url: str, headers: dict[str, str] | None = None, context: ssl.SSLContext | None = None) -> bytes:
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, context=context, timeout=30) as resp:
        return resp.read()


def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def discover_from_env() -> tuple[str | None, str | None]:
    """Return (eda_namespace, chassis_name) from explicit env overrides."""
    ns = os.environ.get("CX_NODE_NAMESPACE") or os.environ.get("EDA_NAMESPACE")
    chassis = os.environ.get("CX_CHASSIS_NAME")
    return (ns, chassis)


def discover_from_pod_name(pod_name: str) -> tuple[str | None, str | None]:
    m = POD_NAME_RE.match(pod_name)
    if not m:
        return (None, None)
    return (m.group("ns"), m.group("chassis"))


def fetch_own_pod(pod_name: str, pod_namespace: str) -> dict:
    if not K8S_API:
        raise RuntimeError("KUBERNETES_SERVICE_HOST is not set; not running in-cluster?")
    if not SA_TOKEN_PATH.is_file():
        raise RuntimeError(f"ServiceAccount token not found at {SA_TOKEN_PATH}")

    token = read_text(SA_TOKEN_PATH)
    url = (
        f"https://{K8S_API}:{K8S_API_PORT}"
        f"/api/v1/namespaces/{pod_namespace}/pods/{pod_name}"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    ctx = ssl_context(cafile=SA_CA_PATH, verify=True)
    raw = http_get(url, headers=headers, context=ctx)
    return json.loads(raw.decode("utf-8"))


def labels_from_pod(pod: dict) -> tuple[str | None, str | None]:
    labels = (pod.get("metadata") or {}).get("labels") or {}
    return (labels.get(LABEL_NAMESPACE), labels.get(LABEL_CHASSIS))


def resolve_identity() -> tuple[str, str]:
    """Determine EDA namespace and chassis name for this SimNode."""
    env_ns, env_chassis = discover_from_env()
    if env_ns and env_chassis:
        log(f"Using identity from environment: namespace={env_ns} chassis={env_chassis}")
        return env_ns, env_chassis

    pod_name = os.environ.get("HOSTNAME")
    if not pod_name:
        raise RuntimeError("HOSTNAME is not set; cannot determine pod name")

    pod_namespace = os.environ.get("POD_NAMESPACE")
    if not pod_namespace:
        if SA_NS_PATH.is_file():
            pod_namespace = read_text(SA_NS_PATH)
        else:
            raise RuntimeError("Pod namespace unknown (set POD_NAMESPACE or mount a ServiceAccount)")

    eda_ns: str | None = env_ns
    chassis: str | None = env_chassis

    try:
        log(f"Fetching pod {pod_namespace}/{pod_name} from Kubernetes API")
        pod = fetch_own_pod(pod_name, pod_namespace)
        api_ns, api_chassis = labels_from_pod(pod)
        eda_ns = eda_ns or api_ns
        chassis = chassis or api_chassis
        if api_ns or api_chassis:
            log(f"Pod labels: {LABEL_NAMESPACE}={api_ns} {LABEL_CHASSIS}={api_chassis}")
    except Exception as exc:
        log(f"Kubernetes API pod lookup failed: {exc}")

    if not eda_ns or not chassis:
        name_ns, name_chassis = discover_from_pod_name(pod_name)
        if name_ns or name_chassis:
            log(f"Parsed identity from pod name: namespace={name_ns} chassis={name_chassis}")
        eda_ns = eda_ns or name_ns
        chassis = chassis or name_chassis

    if not eda_ns or not chassis:
        raise RuntimeError(
            "Unable to determine EDA namespace and chassis name. "
            f"Expected pod labels '{LABEL_NAMESPACE}' and '{LABEL_CHASSIS}', "
            "or set CX_NODE_NAMESPACE and CX_CHASSIS_NAME."
        )

    return eda_ns, chassis


def download_file(url: str, dest: pathlib.Path, context: ssl.SSLContext, retries: int, delay: float) -> None:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            log(f"GET {url} (attempt {attempt}/{retries})")
            data = http_get(url, context=context)
            dest.write_bytes(data)
            log(f"Wrote {dest} ({len(data)} bytes)")
            return
        except urllib.error.HTTPError as exc:
            last_err = exc
            # 404 may mean the Artifact is not published yet — keep retrying.
            log(f"HTTP {exc.code} for {url}: {exc.reason}")
        except Exception as exc:
            last_err = exc
            log(f"Download failed for {url}: {exc}")
        if attempt < retries:
            time.sleep(delay)
    raise RuntimeError(f"Failed to download {url} after {retries} attempts: {last_err}")


def fix_ownership(path: pathlib.Path) -> None:
    """Best-effort chown to frr; vtysh.conf prefers group frrvty when present."""
    user = "frr"
    group = "frrvty" if path.name == "vtysh.conf" else "frr"
    try:
        shutil.chown(path, user=user, group=group)
    except LookupError:
        try:
            shutil.chown(path, user="frr", group="frr")
        except Exception as exc:
            log(f"Warning: could not chown {path}: {exc}")
    except PermissionError as exc:
        log(f"Warning: could not chown {path}: {exc}")
    try:
        path.chmod(0o640)
    except OSError as exc:
        log(f"Warning: could not chmod {path}: {exc}")


def main() -> int:
    eda_ns, chassis = resolve_identity()
    log(f"Resolved SimNode identity: eda_namespace={eda_ns} chassis={chassis}")

    # asvr_base = os.environ.get("ASVR_BASE_URL", "https://eda-asvr.eda-system.svc").rstrip("/")
    asvr_base = "http://eda-api/core/httpproxy/v1/asvr".rstrip("/")
    repo = os.environ.get("ASVR_REPO", "frr-cx-configs")
    config_dir = pathlib.Path(os.environ.get("FRR_CONFIG_DIR", "/etc/frr"))
    retries = int(os.environ.get("CONFIG_FETCH_RETRIES", "30"))
    delay = float(os.environ.get("CONFIG_FETCH_DELAY", "2"))
    verify_tls = env_bool("ASVR_TLS_VERIFY", default=False)

    config_dir.mkdir(parents=True, exist_ok=True)
    ctx = ssl_context(verify=verify_tls)

    for filename, artifact_suffix in CONFIG_ARTIFACTS:
        artifact_name = f"frr-cx-{chassis}-{artifact_suffix}"
        url = f"{asvr_base}/{eda_ns}/{repo}/{artifact_name}/{filename}"
        dest = config_dir / filename
        download_file(url, dest, ctx, retries=retries, delay=delay)
        fix_ownership(dest)

    log("All FRR configuration files fetched successfully")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"FATAL: {exc}")
        sys.exit(1)
