import pytest
from autopsy.core.config import LensConfig
from autopsy.core.decorator import LensDecorator
import autopsy.core.session as session_mod


@pytest.mark.asyncio
async def test_root_async_creates_session_under_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace
    async def agent():
        from autopsy.core.context import current_session
        assert current_session() is not None
        return 1

    assert await agent() == 1


def test_per_call_detectors_override(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "_writer_singleton", None)
    cfg = LensConfig(session_dir=str(tmp_path), default_sample="errors")
    lens = LensDecorator(config=cfg)

    @lens.trace(detectors=[])
    def agent():
        return 1

    assert agent() == 1
