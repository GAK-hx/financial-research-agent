package com.morshan.financial.gateway.filter;

import static org.assertj.core.api.Assertions.assertThat;

import com.morshan.financial.gateway.config.GatewayProperties;
import com.morshan.financial.gateway.security.GatewayAuthenticationToken;
import com.morshan.financial.gateway.security.GatewayIdentity;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.Test;
import org.springframework.mock.http.server.reactive.MockServerHttpRequest;
import org.springframework.mock.web.server.MockServerWebExchange;
import org.springframework.web.server.ServerWebExchange;

class IdentityForwardingGlobalFilterTest {
    @Test
    void invokesDownstreamOnceAndNormalizesTrustedHeaders() {
        GatewayProperties properties = new GatewayProperties();
        properties.setInternalApiKey("internal-secret");
        var filter = new IdentityForwardingGlobalFilter(properties);
        var authentication = new GatewayAuthenticationToken(
                new GatewayIdentity("tenant-a", "user-a", "researcher"));
        var exchange = MockServerWebExchange.builder(MockServerHttpRequest
                        .post("/api/v1/runs")
                        .header("Authorization", "Bearer external-secret")
                        .header("X-Tenant-ID", "spoofed")
                        .header("X-Request-ID", "request-1")
                        .build())
                .principal(authentication)
                .build();
        AtomicInteger calls = new AtomicInteger();
        AtomicReference<ServerWebExchange> forwarded = new AtomicReference<>();

        filter.filter(exchange, downstream -> {
                    calls.incrementAndGet();
                    forwarded.set(downstream);
                    downstream.getResponse().getHeaders().add("x-request-id", "request-1");
                    return downstream.getResponse().setComplete();
                })
                .block();

        assertThat(calls).hasValue(1);
        assertThat(forwarded.get().getRequest().getHeaders().getFirst("X-Tenant-ID"))
                .isEqualTo("tenant-a");
        assertThat(forwarded.get().getRequest().getHeaders().getFirst("X-User-ID"))
                .isEqualTo("user-a");
        assertThat(forwarded.get().getRequest().getHeaders().getFirst("Authorization"))
                .isEqualTo("Bearer internal-secret");
        assertThat(exchange.getResponse().getHeaders().get("X-Request-ID"))
                .containsExactly("request-1");
    }
}
