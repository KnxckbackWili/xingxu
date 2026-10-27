"""Exercise real SPA static serving with a compressible JavaScript bundle."""
import gzip

import pytest


def test_javascript_compression_preserves_bytes_and_cache(client, tmp_path, monkeypatch):
    from app import main
    if not main.FRONTEND_DIST.exists():
        pytest.skip('Build frontend before exercising static serving')
    (tmp_path / 'assets').mkdir()
    source = b'const example = "AGV task render performance";\n' * 500
    (tmp_path / 'assets' / 'test-hash.js').write_bytes(source)
    monkeypatch.setattr(main, 'FRONTEND_DIST', tmp_path)
    with client.stream('GET', '/assets/test-hash.js', headers={'Accept-Encoding': 'gzip'}) as response:
        wire = b''.join(response.iter_raw())
        assert response.status_code == 200
        assert response.headers.get('Content-Encoding') == 'gzip'
        assert 'Accept-Encoding' in response.headers.get('Vary', '')
        assert 'immutable' in response.headers['Cache-Control']
    assert gzip.decompress(wire) == source
    assert len(wire) < len(source) / 2
    plain = client.get('/assets/test-hash.js', headers={'Accept-Encoding': 'identity'})
    assert 'Content-Encoding' not in plain.headers
    assert plain.content == source
    # API / streaming responses do not pass through asset compression.
    assert 'Content-Encoding' not in client.get('/health', headers={'Accept-Encoding': 'gzip'}).headers
