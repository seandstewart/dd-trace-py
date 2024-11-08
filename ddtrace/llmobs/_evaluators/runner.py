from concurrent import futures
import os
from typing import Dict

from ddtrace import Span
from ddtrace.internal import forksafe
from ddtrace.internal.logger import get_logger
from ddtrace.internal.periodic import PeriodicService
from ddtrace.internal.telemetry import telemetry_writer
from ddtrace.internal.telemetry.constants import TELEMETRY_APM_PRODUCT
from ddtrace.llmobs._evaluators.ragas.faithfulness import RagasFaithfulnessEvaluator
from ddtrace.llmobs._evaluators.sampler import EvaluatorRunnerSampler


logger = get_logger(__name__)


SUPPORTED_EVALUATORS = {
    RagasFaithfulnessEvaluator.LABEL: RagasFaithfulnessEvaluator,
}


class EvaluatorRunner(PeriodicService):
    """Base class for evaluating LLM Observability span events
    This class
    1. parses active evaluators from the environment and initializes these evaluators
    2. triggers evaluator runs over buffered finished spans on each `periodic` call
    """

    def __init__(self, interval: float, llmobs_service=None, evaluators=None):
        super(EvaluatorRunner, self).__init__(interval=interval)
        self._lock = forksafe.RLock()
        self._buffer = []  # type: list[tuple[Dict, Span]]
        self._buffer_limit = 1000

        self.llmobs_service = llmobs_service
        self.executor = futures.ThreadPoolExecutor()
        self.sampler = EvaluatorRunnerSampler()
        self.evaluators = [] if evaluators is None else evaluators

        if len(self.evaluators) > 0:
            return

        evaluator_str = os.getenv("_DD_LLMOBS_EVALUATORS")
        if evaluator_str is None:
            return

        evaluators = evaluator_str.split(",")
        for evaluator in evaluators:
            if evaluator in SUPPORTED_EVALUATORS:
                evaluator_init_state = "ok"
                try:
                    self.evaluators.append(SUPPORTED_EVALUATORS[evaluator](llmobs_service=llmobs_service))
                except NotImplementedError as e:
                    evaluator_init_state = "error"
                    raise e
                finally:
                    telemetry_writer.add_count_metric(
                        namespace=TELEMETRY_APM_PRODUCT.LLMOBS,
                        name="evaluators.init",
                        value=1,
                        tags=(
                            ("evaluator_label", evaluator),
                            ("state", evaluator_init_state),
                        ),
                    )

    def start(self, *args, **kwargs):
        if not self.evaluators:
            logger.debug("no evaluators configured, not starting %r", self.__class__.__name__)
            return
        super(EvaluatorRunner, self).start()
        logger.debug("started %r to %r", self.__class__.__name__)

    def _stop_service(self) -> None:
        """
        Ensures all spans are evaluated & evaluation metrics are submitted when evaluator runner
        is stopped by the LLM Obs instance
        """
        self.periodic(_wait_sync=True)
        self.executor.shutdown(wait=True)

    def recreate(self) -> "EvaluatorRunner":
        return self.__class__(
            interval=self._interval,
            llmobs_service=self.llmobs_service,
            evaluators=self.evaluators,
        )

    def enqueue(self, span_event: Dict, span: Span) -> None:
        with self._lock:
            if len(self._buffer) >= self._buffer_limit:
                logger.warning(
                    "%r event buffer full (limit is %d), dropping event", self.__class__.__name__, self._buffer_limit
                )
                return
            self._buffer.append((span_event, span))

    def periodic(self, _wait_sync=False) -> None:
        """
        :param bool _wait_sync: if `True`, each evaluator is run for each span in the buffer
        synchronously. This param is only set to `True` for when the evaluator runner is stopped by the LLM Obs
        instance on process exit and we want to block until all spans are evaluated and metrics are submitted.
        """
        with self._lock:
            if not self._buffer:
                return
            span_events_and_spans = self._buffer  # type: list[tuple[Dict, Span]]
            self._buffer = []

        try:
            if not _wait_sync:
                for evaluator in self.evaluators:
                    self.executor.map(
                        lambda span_event: evaluator.run_and_submit_evaluation(span_event),
                        [
                            span_event
                            for span_event, span in span_events_and_spans
                            if self.sampler.sample(evaluator.LABEL, span)
                        ],
                    )
            else:
                for evaluator in self.evaluators:
                    for span_event, span in span_events_and_spans:
                        if self.sampler.sample(evaluator.LABEL, span):
                            evaluator.run_and_submit_evaluation(span_event)
        except RuntimeError as e:
            logger.debug("failed to run evaluation: %s", e)