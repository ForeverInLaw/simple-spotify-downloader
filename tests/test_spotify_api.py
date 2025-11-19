import pytest

from modules.spotify_api import SpotifyClient


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://open.spotify.com/track/1234567890abcdef", "1234567890abcdef"),
        (
            "https://open.spotify.com/track/abcdefghijklmno?si=deadbeef",
            "abcdefghijklmno",
        ),
        (
            "https://open.spotify.com/intl-en/track/1234567890abcdef",
            "1234567890abcdef",
        ),
        (
            "https://open.spotify.com/track/abcdefghijklmno/",
            "abcdefghijklmno",
        ),
        ("spotify:track:zzYYxx1122", "zzYYxx1122"),
        ("https://open.spotify.com/playlist/abc", None),
        ("not a link", None),
    ],
)
def test_extract_track_id(text, expected):
    assert SpotifyClient.extract_track_id(text) == expected


def test_is_spotify_link_relies_on_extract(monkeypatch):
    called = {}

    def fake_extract(value):
        """
        Record the provided value into the shared `called` mapping and return a fixed test ID.
        
        Parameters:
            value: The input value to store in `called["value"]`.
        
        Returns:
            str: The constant string `"id123"`.
        """
        called["value"] = value
        return "id123"

    monkeypatch.setattr(SpotifyClient, "extract_track_id", staticmethod(fake_extract))

    assert SpotifyClient.is_spotify_link("dummy text") is True
    assert called["value"] == "dummy text"

    monkeypatch.setattr(SpotifyClient, "extract_track_id", staticmethod(lambda _: None))
    assert SpotifyClient.is_spotify_link("dummy text") is False