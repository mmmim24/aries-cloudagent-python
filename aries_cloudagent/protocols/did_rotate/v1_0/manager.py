"""DID Rotate manager.

Manages and tracks the state of the DID Rotate protocol.
"""

from ....connections.base_manager import (
    BaseConnectionManager,
    BaseConnectionManagerError,
)
from ....connections.models.conn_record import ConnRecord
from ....core.profile import Profile
from ....messaging.responder import BaseResponder
from ....resolver.base import DIDMethodNotSupported, DIDNotFound
from ....resolver.did_resolver import DIDResolver
from .messages import RotateProblemReport, Rotate, RotateAck
from .models import RotateRecord


class DIDRotateManagerError(Exception):
    """Raised when an error occurs during a DID Rotate protocol flow."""


class ReportableDIDRotateError(DIDRotateManagerError):
    """Base class for reportable errors."""

    def __init__(self, message: RotateProblemReport):
        """Initialize the ReportableDIDRotateError."""
        self.message = message


class UnresolvableDIDError(ReportableDIDRotateError):
    """Raised when a DID cannot be resolved."""


class UnsupportedDIDMethodError(ReportableDIDRotateError):
    """Raised when a DID method is not supported."""


class DIDRotateManager:
    """DID Rotate Manager.

    Manages and tracks the state of the DID Rotate protocol.

    This mechanism allows a party in a relationship to change the DID they use
    to identify themselves in that relationship. This may be used to switch DID
    methods, but also to switch to a new DID within the same DID method. For
    non-updatable DID methods, this allows updating DID Doc attributes such as
    service endpoints. Inspired by (but different from) the DID rotation
    feature of the DIDComm Messaging (DIDComm v2) spec.

    DID Rotation is a pre-rotate operation. We send notification of rotation
    to the observing party before we rotate the DID. This allows the observing
    party to update their DID for the rotating party and notify the rotating
    party of any issues with the recieved DID.

    DID Rotation has two roles: the rotating party and the observing party.

    This manager is responsible for both of the possible roles in the protocol.
    """

    def __init__(self, profile: Profile):
        """Initialize DID Rotate Manager."""
        self.profile = profile

    async def rotate_my_did(self, conn: ConnRecord, new_did: str):
        """Rotate my DID.

        Args:
            conn (ConnRecord): The connection to rotate the DID for.
            new_did (str): The new DID to use for the connection.
        """

        record = RotateRecord(
            role=RotateRecord.ROLE_ROTATING,
            state=RotateRecord.STATE_ROTATE_SENT,
            connection_id=conn.connection_id,
            new_did=new_did,
        )
        rotate = Rotate(to_did=new_did)
        record.thread_id = rotate._message_id

        responder = self.profile.inject(BaseResponder)
        await responder.send(rotate, connection_id=conn.connection_id)

        async with self.profile.session() as session:
            await record.save(session, reason="Sent rotate message")

    async def ensure_supported_did(self, did: str):
        """Check if the DID is supported."""
        resolver = self.profile.inject(DIDResolver)
        conn_mgr = BaseConnectionManager(self.profile)
        try:
            await resolver.resolve(self.profile, did)
        except DIDMethodNotSupported:
            raise UnsupportedDIDMethodError(RotateProblemReport.method_unsupported(did))
        except DIDNotFound:
            raise UnresolvableDIDError(RotateProblemReport.unresolvable(did))

        try:
            await conn_mgr.resolve_didcomm_services(did)
        except BaseConnectionManagerError:
            # TODO Make this reportable?
            raise DIDRotateManagerError("Unable to resolve DIDComm services for DID")

    async def receive_rotate(self, conn: ConnRecord, rotate: Rotate):
        """Receive rotate message.

        Args:
            conn (ConnRecord): The connection to rotate the DID for.
            rotate (Rotate): The received rotate message.
        """
        record = RotateRecord(
            role=RotateRecord.ROLE_OBSERVING,
            state=RotateRecord.STATE_ROTATE_RECEIVED,
            connection_id=conn.connection_id,
            new_did=rotate.to_did,
            thread_id=rotate._message_id,
        )

        try:
            await self.ensure_supported_did(rotate.to_did)
        except ReportableDIDRotateError as err:
            responder = self.profile.inject(BaseResponder)
            await responder.send(err.message, connection_id=conn.connection_id)

        async with self.profile.session() as session:
            await record.save(session, reason="Received rotate message")

    async def commit_rotate(self, conn: ConnRecord, record: RotateRecord):
        """Commit rotate.

        Args:
            conn (ConnRecord): The connection to rotate the DID for.
            record (RotateRecord): The rotate record.
        """
        record.state = RotateRecord.STATE_ACK_SENT
        if not record.new_did:
            raise ValueError("No new DID stored in record")

        conn_mgr = BaseConnectionManager(self.profile)
        try:
            await conn_mgr.record_keys_for_resolvable_did(record.new_did)
        except BaseConnectionManagerError as err:
            # TODO Make this reportable?
            raise DIDRotateManagerError(
                "Unable to record keys for resolvable DID"
            ) from err

        conn.their_did = record.new_did

        ack = RotateAck()
        ack.assign_thread_id(thid=record.thread_id)

        responder = self.profile.inject(BaseResponder)
        await responder.send(ack, connection_id=conn.connection_id)

        async with self.profile.session() as session:
            # Don't emit a connection event for this change
            # Controllers should listen for the rotate event instead
            await conn.save(session, reason="Their DID rotated", event=False)
            await record.save(session, reason="Sent rotate ack")

    async def receive_ack(self, conn: ConnRecord, ack: RotateAck):
        """Receive rotate ack message.

        Args:
            conn (ConnRecord): The connection to rotate the DID for.
            ack (RotateAck): The received rotate ack message.
        """

    async def receive_problem_report(
        self, conn: ConnRecord, problem_report: RotateProblemReport
    ):
        """Receive problem report message.

        Args:
            conn (ConnRecord): The connection to rotate the DID for.
            problem_report (ProblemReport): The received problem report message.
        """
