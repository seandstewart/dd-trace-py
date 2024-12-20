from mock import PropertyMock
from mock import patch as mock_patch
import pytest

from ddtrace.contrib.vertexai import patch
from ddtrace.contrib.vertexai import unpatch
from ddtrace.pin import Pin
from tests.contrib.vertexai.utils import MockAsyncPredictionServiceClient
from tests.contrib.vertexai.utils import MockPredictionServiceClient
from tests.utils import DummyTracer
from tests.utils import DummyWriter
from tests.utils import override_config
from tests.utils import override_global_config


@pytest.fixture
def ddtrace_global_config():
    return {}


@pytest.fixture
def ddtrace_config_vertexai():
    return {}


@pytest.fixture
def mock_client():
    yield MockPredictionServiceClient()


@pytest.fixture
def mock_async_client():
    yield MockAsyncPredictionServiceClient()


@pytest.fixture
def mock_tracer(vertexai):
    try:
        pin = Pin.get_from(vertexai)
        mock_tracer = DummyTracer(writer=DummyWriter(trace_flush_enabled=False))
        pin.override(vertexai, tracer=mock_tracer)
        pin.tracer.configure()
        yield mock_tracer
    except Exception:
        yield


@pytest.fixture
def vertexai(ddtrace_global_config, ddtrace_config_vertexai, mock_client, mock_async_client):
    global_config = ddtrace_global_config
    with override_global_config(global_config):
        with override_config("vertexai", ddtrace_config_vertexai):
            patch()
            import vertexai
            from vertexai.generative_models import GenerativeModel

            with mock_patch.object(
                GenerativeModel, "_prediction_client", new_callable=PropertyMock
            ) as mock_client_property, mock_patch.object(
                GenerativeModel, "_prediction_async_client", new_callable=PropertyMock
            ) as mock_async_client_property:
                mock_client_property.return_value = mock_client
                mock_async_client_property.return_value = mock_async_client
                yield vertexai

            unpatch()
