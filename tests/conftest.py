import pytest


@pytest.fixture
def setting(tmp_path):
    file = tmp_path / "delivery.compressorsetting"
    file.write_text('''<setting name="Delivery"><encoder name="QT">
      <file-extension>mov</file-extension><video-encode isEnabled="yes">
      <bounds width="-100" height="-100"/><frame-rate>-100</frame-rate>
      <codec-type>hvc1</codec-type></video-encode></encoder></setting>''')
    return file
