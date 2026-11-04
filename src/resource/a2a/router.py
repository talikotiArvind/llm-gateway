"""A2ARouter — peer-local dispatch with trace logging and error boundary."""

from __future__ import annotations

import logging
import time

from src.resource.a2a.protocol import A2AMessage, A2APeer, A2AResponse

logger = logging.getLogger(__name__)


class A2ARouter:
    """Dispatch A2AMessages to registered peer agents.

    Scope is peer-local: only peers explicitly declared on an agent are reachable.
    No global registry — prevents accidental cross-talk between unrelated agents.
    """

    def __init__(self, peers: list[A2APeer]) -> None:
        """Initialize the router with a peer-local registry.

        Args:
            peers (list[A2APeer]): Peer agents this router is allowed to dispatch to.
        """
        self._registry: dict[str, A2APeer] = {p.name: p for p in peers}

    # ------------------------------------------------------------------
    # Synchronous dispatch
    # ------------------------------------------------------------------

    def dispatch(self, peer_name: str, message: A2AMessage) -> A2AResponse:
        """Route a message to the named peer and return its response.

        Args:
            peer_name (str): Logical name of the registered peer to dispatch to.
            message (A2AMessage): Envelope containing the payload to deliver.

        Returns:
            A2AResponse: The peer agent's response, including timing metadata.

        Raises:
            KeyError: If peer_name is not registered.
            Exception: Propagates any exception raised by the peer agent, after
                logging it.
        """
        peer = self._resolve(peer_name)
        start = time.monotonic()

        logger.info(
            "a2a.dispatch",
            extra={
                "trace_id": message.trace_id,
                "sender": message.sender,
                "peer": peer_name,
                "peer_agent_id": peer.agent.agent_id,
            },
        )

        try:
            output: str = peer.agent.run(message.payload)
        except Exception:
            logger.exception(
                "a2a.dispatch.error",
                extra={"trace_id": message.trace_id, "peer": peer_name},
            )
            raise

        duration_ms = (time.monotonic() - start) * 1000

        logger.info(
            "a2a.dispatch.complete",
            extra={
                "trace_id": message.trace_id,
                "peer": peer_name,
                "duration_ms": round(duration_ms, 2),
            },
        )

        return A2AResponse(
            message_id=message.id,
            sender=peer.agent.agent_id,
            output=output,
            trace_id=message.trace_id,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Asynchronous dispatch
    # ------------------------------------------------------------------

    async def dispatch_async(self, peer_name: str, message: A2AMessage) -> A2AResponse:
        """Route a message to the named peer asynchronously.

        Async variant of :meth:`dispatch` — calls ``peer.run_async()`` for
        non-blocking delegation.

        Args:
            peer_name (str): Logical name of the registered peer to dispatch to.
            message (A2AMessage): Envelope containing the payload to deliver.

        Returns:
            A2AResponse: The peer agent's response, including timing metadata.

        Raises:
            KeyError: If peer_name is not registered.
            Exception: Propagates any exception raised by the peer agent, after
                logging it.
        """
        peer = self._resolve(peer_name)
        start = time.monotonic()

        logger.info(
            "a2a.dispatch_async",
            extra={"trace_id": message.trace_id, "sender": message.sender, "peer": peer_name},
        )

        try:
            output: str = await peer.agent.run_async(message.payload)
        except Exception:
            logger.exception(
                "a2a.dispatch_async.error",
                extra={"trace_id": message.trace_id, "peer": peer_name},
            )
            raise

        duration_ms = (time.monotonic() - start) * 1000

        return A2AResponse(
            message_id=message.id,
            sender=peer.agent.agent_id,
            output=output,
            trace_id=message.trace_id,
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve(self, peer_name: str) -> A2APeer:
        """Look up a registered peer by name.

        Args:
            peer_name (str): Logical name of the peer to resolve.

        Returns:
            A2APeer: The registered peer matching peer_name.

        Raises:
            KeyError: If peer_name is not registered.
        """
        if peer_name not in self._registry:
            available = sorted(self._registry)
            raise KeyError(
                f"No peer named '{peer_name}' registered. Available: {available}"
            )
        return self._registry[peer_name]

    @property
    def registered_peers(self) -> list[str]:
        """Return the sorted list of registered peer names.

        Returns:
            list[str]: Sorted peer names currently registered with this router.
        """
        return sorted(self._registry)
