# Financial Agent Backend Gateway

Spring Boot/WebFlux access layer for the Python financial research Agent.

Responsibilities:

- authenticate external API key or JWT credentials;
- resolve a trusted tenant/user/role;
- discard spoofed identity headers and write internal headers;
- apply Redis-backed token-bucket rate limits;
- fail closed for new analysis when the Redis rate-limit backend is unavailable;
- attach request and idempotency identifiers;
- proxy `/api/v1/**` and SSE responses to the internal Python Job API;
- expose Actuator readiness and Prometheus metrics.

It does not implement LangGraph, Tools, Skills, Evidence analysis or report generation.

The normal local build uses Docker and does not require Maven or Java 21 on the host.
`GATEWAY_INTERNAL_API_KEY` is required; the process fails at startup when it is absent.
