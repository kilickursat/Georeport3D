from dataclasses import replace

import pytest

from georeport3d.services.cache import CacheKeyParts, make_cache_key


def test_model_revision_changes_cache_key() -> None:
    base = dict(
        document_sha256="doc",
        figure_sha256="figure",
        model_id="model",
        prompt_version="v1",
        preprocess_version="v1",
    )
    assert make_cache_key(CacheKeyParts(**base, model_revision="a")) != make_cache_key(
        CacheKeyParts(**base, model_revision="b")
    )


def test_delimiter_relocation_changes_cache_key() -> None:
    common = dict(
        document_sha256="doc",
        figure_sha256="figure",
        prompt_version="prompt",
        preprocess_version="preprocess",
    )
    left = CacheKeyParts(**common, model_id="model|revision", model_revision="r1")
    right = CacheKeyParts(**common, model_id="model", model_revision="revision|r1")

    assert left != right
    assert make_cache_key(left) != make_cache_key(right)


def test_missing_empty_and_literal_unversioned_revisions_have_distinct_keys() -> None:
    common = dict(
        document_sha256="doc",
        figure_sha256="figure",
        model_id="model",
        prompt_version="prompt",
        preprocess_version="preprocess",
    )
    keys = {
        make_cache_key(CacheKeyParts(**common, model_revision=revision))
        for revision in (None, "", "unversioned")
    }

    assert len(keys) == 3


def test_cache_key_matches_independent_fixed_vector() -> None:
    parts = CacheKeyParts(
        document_sha256="doc",
        figure_sha256="figure",
        model_id="model",
        model_revision="revision",
        prompt_version="prompt-v1",
        preprocess_version="pre-v1",
    )

    assert make_cache_key(parts) == (
        "3ba2e12ea592fc7a6b5d931b31d08fb6ef5ae7f74badef5356bbebc8a0a420ee"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("document_sha256", "doc-2"),
        ("figure_sha256", "figure-2"),
        ("model_id", "model-2"),
        ("model_revision", "revision-2"),
        ("prompt_version", "prompt-v2"),
        ("preprocess_version", "pre-v2"),
    ),
)
def test_every_cache_component_changes_key(field: str, value: str) -> None:
    base = CacheKeyParts(
        document_sha256="doc",
        figure_sha256="figure",
        model_id="model",
        model_revision="revision",
        prompt_version="prompt-v1",
        preprocess_version="pre-v1",
    )

    assert make_cache_key(replace(base, **{field: value})) != make_cache_key(base)
