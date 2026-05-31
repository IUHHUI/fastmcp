"""Compatibility patches for the upstream MCP Python SDK session layer."""

from __future__ import annotations

import logging

from mcp import types
from mcp.shared import session as mcp_session
from pydantic import ValidationError

logger = logging.getLogger(__name__)

_PATCH_ATTR = "_fastmcp_catches_invalid_client_requests"
_ORIGINAL_ATTR = "_fastmcp_original_receive_loop"


async def _receive_loop_with_invalid_request_handling(self) -> None:
    async with (
        self._read_stream,
        self._write_stream,
    ):
        async for message in self._read_stream:
            if isinstance(message, Exception):
                await self._handle_incoming(message)
            elif isinstance(message.message.root, mcp_session.JSONRPCRequest):
                try:
                    validated_request = self._receive_request_type.model_validate(
                        message.message.root.model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        )
                    )
                except ValidationError as e:
                    logger.warning(
                        "Failed to validate request: %s. Message was: %s",
                        e,
                        message.message.root,
                    )
                    await self._send_response(
                        message.message.root.id,
                        types.ErrorData(
                            code=types.INVALID_REQUEST,
                            message="Invalid request",
                        ),
                    )
                    continue

                responder = mcp_session.RequestResponder(
                    request_id=message.message.root.id,
                    request_meta=validated_request.root.params.meta
                    if validated_request.root.params
                    else None,
                    request=validated_request,
                    session=self,
                    on_complete=lambda r: self._in_flight.pop(r.request_id, None),
                    message_metadata=message.metadata,
                )

                self._in_flight[responder.request_id] = responder
                await self._received_request(responder)

                if not responder._completed:  # type: ignore[reportPrivateUsage]
                    await self._handle_incoming(responder)

            elif isinstance(message.message.root, mcp_session.JSONRPCNotification):
                try:
                    notification = self._receive_notification_type.model_validate(
                        message.message.root.model_dump(
                            by_alias=True, mode="json", exclude_none=True
                        )
                    )
                    if isinstance(notification.root, mcp_session.CancelledNotification):
                        cancelled_id = notification.root.params.requestId
                        if cancelled_id in self._in_flight:
                            await self._in_flight[cancelled_id].cancel()
                    else:
                        if isinstance(
                            notification.root, mcp_session.ProgressNotification
                        ):
                            progress_token = notification.root.params.progressToken
                            if progress_token in self._progress_callbacks:
                                callback = self._progress_callbacks[progress_token]
                                await callback(
                                    notification.root.params.progress,
                                    notification.root.params.total,
                                    notification.root.params.message,
                                )
                        await self._received_notification(notification)
                        await self._handle_incoming(notification)
                except Exception as e:
                    logger.warning(
                        "Failed to validate notification: %s. Message was: %s",
                        e,
                        message.message.root,
                    )
            else:
                stream = self._response_streams.pop(message.message.root.id, None)
                if stream:
                    await stream.send(message.message.root)
                else:
                    await self._handle_incoming(
                        RuntimeError(
                            "Received response with an unknown "
                            f"request ID: {message}"
                        )
                    )

        for id, stream in self._response_streams.items():
            error = types.ErrorData(
                code=types.CONNECTION_CLOSED,
                message="Connection closed",
            )
            await stream.send(
                mcp_session.JSONRPCError(jsonrpc="2.0", id=id, error=error)
            )
            await stream.aclose()
        self._response_streams.clear()


def patch_mcp_session_invalid_request_handling() -> None:
    """Prevent invalid client requests from escaping MCP's receive task group."""
    receive_loop = mcp_session.BaseSession._receive_loop
    if getattr(receive_loop, _PATCH_ATTR, False):
        return

    setattr(mcp_session.BaseSession, _ORIGINAL_ATTR, receive_loop)
    setattr(_receive_loop_with_invalid_request_handling, _PATCH_ATTR, True)
    mcp_session.BaseSession._receive_loop = _receive_loop_with_invalid_request_handling
