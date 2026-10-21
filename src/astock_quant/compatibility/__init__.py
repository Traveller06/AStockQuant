"""Compatibility helpers for read-only inspection of legacy releases."""

from .legacy_v7 import LegacyArtifact, LegacyInventory, discover_legacy, sha256_path

__all__ = ["LegacyArtifact", "LegacyInventory", "discover_legacy", "sha256_path"]
