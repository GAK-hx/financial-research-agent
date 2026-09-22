package com.morshan.financial.gateway.filter;

import com.morshan.financial.gateway.config.GatewayProperties;
import com.morshan.financial.gateway.security.GatewayAuthenticationToken;
import com.morshan.financial.gateway.security.GatewayIdentity;
import java.util.List;
import java.util.UUID;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

@Component
public class IdentityForwardingGlobalFilter implements GlobalFilter, Ordered {
    private static final List<String> UNTRUSTED_HEADERS = List.of(
            "X-Tenant-ID",
            "X-User-ID",
            "X-Agent-Role",
            "X-Internal-Principal");

    private final GatewayProperties properties;

    public IdentityForwardingGlobalFilter(GatewayProperties properties) {
        this.properties = properties;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String requestId = exchange.getRequest().getHeaders().getFirst("X-Request-ID");
        if (requestId == null || !requestId.matches("[a-zA-Z0-9_.-]{1,128}")) {
            requestId = UUID.randomUUID().toString().replace("-", "");
        }
        String idempotency = exchange.getRequest().getHeaders().getFirst("Idempotency-Key");
        boolean idempotentEndpoint = exchange.getRequest().getMethod().name().equals("POST")
                && (exchange.getRequest().getPath().value().equals("/api/v1/runs")
                || exchange.getRequest().getPath().value().equals("/api/v1/analyze"));
        if (idempotency != null && idempotency.length() > 128) {
            exchange.getResponse().setStatusCode(HttpStatus.UNPROCESSABLE_ENTITY);
            exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
            byte[] body = "{\"error\":{\"code\":\"INVALID_IDEMPOTENCY_KEY\",\"message\":\"Idempotency-Key must be at most 128 characters\"}}"
                    .getBytes(java.nio.charset.StandardCharsets.UTF_8);
            return exchange.getResponse().writeWith(Mono.just(
                    exchange.getResponse().bufferFactory().wrap(body)));
        }
        if (idempotentEndpoint && (idempotency == null || idempotency.isBlank())) {
            idempotency = UUID.randomUUID().toString();
        }
        String finalRequestId = requestId;
        String finalIdempotency = idempotency;

        return exchange.getPrincipal()
                .ofType(GatewayAuthenticationToken.class)
                .map(authentication -> {
                    GatewayIdentity identity = authentication.getPrincipal();
                    var request = exchange.getRequest().mutate().headers(headers -> {
                        UNTRUSTED_HEADERS.forEach(headers::remove);
                        headers.remove(HttpHeaders.AUTHORIZATION);
                        headers.setBearerAuth(properties.getInternalApiKey());
                        headers.set("X-Tenant-ID", identity.tenantId());
                        headers.set("X-User-ID", identity.userId());
                        headers.set("X-Agent-Role", identity.role());
                        headers.set("X-Request-ID", finalRequestId);
                        if (finalIdempotency != null) {
                            headers.set("Idempotency-Key", finalIdempotency);
                        }
                    }).build();
                    var response = exchange.getResponse();
                    response.beforeCommit(() -> {
                        // Normalize downstream headers instead of appending a
                        // second value when Python echoes the same request id.
                        response.getHeaders().set("X-Request-ID", finalRequestId);
                        if (finalIdempotency != null) {
                            response.getHeaders().set("Idempotency-Key", finalIdempotency);
                        }
                        return Mono.empty();
                    });
                    return exchange.mutate().request(request).build();
                })
                .defaultIfEmpty(exchange)
                .flatMap(chain::filter);
    }

    @Override
    public int getOrder() {
        return -100;
    }
}
