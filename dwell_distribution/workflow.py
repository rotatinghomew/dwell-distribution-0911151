from __future__ import annotations

from .latent import DEFAULT_LONG_STAY_THRESHOLD, latent_analysis
from .product import summarize


def publish_overview(client, as_of, request_key):
    snapshot = client.snapshot(as_of)
    policy = client.policy()
    artifact = {
        "as_of": as_of,
        "snapshot_id": snapshot["snapshot_id"],
        "method": "observed-overview-v1",
        "result": summarize(snapshot),
    }
    return client.publish(request_key, artifact, policy["revision"])


def publish_latent_analysis(client, as_of, request_key, long_stay_threshold=DEFAULT_LONG_STAY_THRESHOLD):
    snapshot = client.snapshot(as_of)
    policy = client.policy()
    artifact = {
        "as_of": as_of,
        "snapshot_id": snapshot["snapshot_id"],
        "method": "latent-dwell-bounds-v1",
        "result": latent_analysis(snapshot, long_stay_threshold=long_stay_threshold),
    }
    return client.publish(request_key, artifact, policy["revision"])
