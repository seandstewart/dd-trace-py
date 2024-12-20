from typing import Any
from typing import Dict
from typing import List
from typing import Set

from ddtrace._trace._span_pointer import _SpanPointerDescription
from ddtrace._trace.utils_botocore.span_pointers.dynamodb import _DynamoDBItemFieldName
from ddtrace._trace.utils_botocore.span_pointers.dynamodb import _DynamoDBTableName
from ddtrace._trace.utils_botocore.span_pointers.dynamodb import _extract_span_pointers_for_dynamodb_response

# We are importing this function here because it used to live in this module
# and was imported from here in datadog-lambda-python. Once the import is fixed
# in the next release of that library, we should be able to remove this unused
# import from here as well.
from ddtrace._trace.utils_botocore.span_pointers.s3 import _aws_s3_object_span_pointer_description  # noqa: F401
from ddtrace._trace.utils_botocore.span_pointers.s3 import _extract_span_pointers_for_s3_response
from ddtrace._trace.utils_botocore.span_pointers.telemetry import record_span_pointer_calculation
from ddtrace._trace.utils_botocore.span_pointers.telemetry import record_span_pointer_calculation_issue
from ddtrace.internal.logger import get_logger


log = get_logger(__name__)


def extract_span_pointers_from_successful_botocore_response(
    dynamodb_primary_key_names_for_tables: Dict[_DynamoDBTableName, Set[_DynamoDBItemFieldName]],
    endpoint_name: str,
    operation_name: str,
    request_parameters: Dict[str, Any],
    response: Dict[str, Any],
) -> List[_SpanPointerDescription]:
    result = []

    try:
        if endpoint_name == "s3":
            result = _extract_span_pointers_for_s3_response(operation_name, request_parameters, response)

        elif endpoint_name == "dynamodb":
            result = _extract_span_pointers_for_dynamodb_response(
                dynamodb_primary_key_names_for_tables, operation_name, request_parameters, response
            )

    except Exception as e:
        # Catch-all in case we miss something in the helpers
        log.debug("span pointers: Error extracting span pointers from botocore response: %s", e)
        record_span_pointer_calculation_issue("extractor_root", "unexpected_error")

    record_span_pointer_calculation(span_pointer_count=len(result))

    return result
