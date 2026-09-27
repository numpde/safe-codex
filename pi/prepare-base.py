"""Reuse the phase-one checksum-verified WLAN image downloader."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("download", "/bootstrap/wlan-download.py")
download = importlib.util.module_from_spec(spec)
spec.loader.exec_module(download)
download.bind_interface("wlp10s0")
download.REGISTRY = "https://registry-1.docker.io/v2/library/node"
download.IMAGE_DIGEST = "sha256:83f1c388c31fb2e51f7cbd4dea949b96260798c98f206e8e4696bc93bd964e3a"
download.IMAGE_TAG = "safe-pi-node:24-83f1c388"


def headers():
    token = download.get_json("https://auth.docker.io/token?service=registry.docker.io"
                              "&scope=repository:library/node:pull")["token"]
    return {"Authorization": "Bearer " + token,
            "Accept": "application/vnd.oci.image.manifest.v1+json"}


download.registry_headers = headers
download.image(Path("/output"))
