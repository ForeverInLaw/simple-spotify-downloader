import os

import pytest

from modules import downloader


@pytest.fixture()
def temp_download_dirs(monkeypatch, tmp_path):
    root = tmp_path / "downloads"
    tracks = root / "tracks"
    covers = root / "covers"
    tracks.mkdir(parents=True)
    covers.mkdir(parents=True)

    monkeypatch.setattr(downloader, "DOWNLOADS_ROOT", root)
    monkeypatch.setattr(downloader, "TRACKS_DIR", tracks)
    monkeypatch.setattr(downloader, "COVERS_DIR", covers)

    return root, tracks, covers


def _write_fake_track(tracks_dir, covers_dir, track_id, size):
    track_path = tracks_dir / f"{track_id}.mp3"
    track_path.write_bytes(b"0" * size)
    os.utime(track_path, (track_id, track_id))

    cover_path = covers_dir / f"{track_id}.jpg"
    cover_path.write_bytes(b"1")


def test_enforce_storage_quota_removes_oldest_tracks(monkeypatch, temp_download_dirs):
    _, tracks, covers = temp_download_dirs

    removed_tracks = []
    monkeypatch.setattr(
        downloader.database,
        "delete_track",
        lambda track_id: removed_tracks.append(track_id),
    )

    for idx in range(3):
        _write_fake_track(tracks, covers, idx, size=600_000)

    worker = downloader.Downloader(max_storage_mb=1)
    worker._enforce_storage_quota()

    remaining = sorted(p.name for p in tracks.glob("*.mp3"))
    assert remaining == ["2.mp3"], "Newest track should remain in cache"

    assert removed_tracks == ["0", "1"], "Older tracks should be evicted first"
    assert not (covers / "0.jpg").exists()
    assert not (covers / "1.jpg").exists()
    assert (covers / "2.jpg").exists()
