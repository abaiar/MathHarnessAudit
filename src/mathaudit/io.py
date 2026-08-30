"""Canonical JSON and JSONL input/output helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator, Union

from .models import Episode

PathLike = Union[str, Path]


def read_episodes(path: PathLike) -> Iterator[Episode]:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        with source.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    yield Episode.model_validate_json(line)
                except Exception as exc:
                    raise ValueError("%s:%d: %s" % (source, line_number, exc)) from exc
        return
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        for item in payload:
            yield Episode.model_validate(item)
    else:
        yield Episode.model_validate(payload)


def write_episodes(path: PathLike, episodes: Iterable[Episode]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".jsonl":
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            for episode in episodes:
                handle.write(episode.model_dump_json(exclude_none=False))
                handle.write("\n")
        return
    payload = [episode.model_dump(mode="json", exclude_none=False) for episode in episodes]
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
