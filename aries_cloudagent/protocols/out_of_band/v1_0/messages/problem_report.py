"""Represents an OOB connection reuse problem report message."""

import logging

from enum import Enum

from marshmallow import (
    EXCLUDE,
    pre_dump,
    validates_schema,
    ValidationError,
)
from string import Template

from ....problem_report.v1_0.message import ProblemReport, ProblemReportSchema

from ..message_types import PROBLEM_REPORT, PROTOCOL_PACKAGE

HANDLER_CLASS = (
    f"{PROTOCOL_PACKAGE}.handlers"
    ".problem_report_handler.OOBProblemReportMessageHandler"
)

LOGGER = logging.getLogger(__name__)
BASE_PROTO_VERSION = "1.0"


class ProblemReportReason(Enum):
    """Supported reason codes."""

    NO_EXISTING_CONNECTION = "no_existing_connection"
    EXISTING_CONNECTION_NOT_ACTIVE = "existing_connection_not_active"


class OOBProblemReport(ProblemReport):
    """Base class representing an OOB connection reuse problem report message."""

    class Meta:
        """OOB connection reuse problem report metadata."""

        handler_class = HANDLER_CLASS
        message_type = PROBLEM_REPORT
        schema_class = "OOBProblemReportSchema"

    def __init__(self, version: str = BASE_PROTO_VERSION, *args, **kwargs):
        """Initialize a ProblemReport message instance."""
        super().__init__(*args, **kwargs)
        self.assign_version_to_message_type(version=version)

    @classmethod
    def assign_version_to_message_type(cls, version: str):
        """Assign version to Meta.message_type."""
        cls.Meta.message_type = Template(cls.Meta.message_type).substitute(
            version=version
        )


class OOBProblemReportSchema(ProblemReportSchema):
    """Schema for ProblemReport base class."""

    class Meta:
        """Metadata for problem report schema."""

        model_class = OOBProblemReport
        unknown = EXCLUDE

    @pre_dump
    def check_thread_deco(self, obj, **kwargs):
        """Thread decorator, and its thid and pthid, are mandatory."""

        if not obj._decorators.to_dict().get("~thread", {}).keys() >= {"thid", "pthid"}:
            raise ValidationError("Missing required field(s) in thread decorator")

        return obj

    @validates_schema
    def validate_fields(self, data, **kwargs):
        """Validate schema fields."""

        if not data.get("description", {}).get("code", ""):
            raise ValidationError("Value for description.code must be present")
        elif data.get("description", {}).get("code", "") not in [
            prr.value for prr in ProblemReportReason
        ]:
            locales = list(data.get("description").keys())
            locales.remove("code")
            LOGGER.warning(
                "Unexpected error code received.\n"
                f"Code: {data.get('description').get('code')}, "
                f"Description: {data.get('description').get(locales[0])}"
            )
