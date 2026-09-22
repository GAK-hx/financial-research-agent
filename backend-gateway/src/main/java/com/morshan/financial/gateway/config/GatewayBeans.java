package com.morshan.financial.gateway.config;

import com.morshan.financial.gateway.security.GatewayAuthenticationToken;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import org.springframework.cloud.gateway.filter.ratelimit.KeyResolver;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class GatewayBeans {
    @Bean
    KeyResolver gatewayKeyResolver() {
        return exchange -> exchange.getPrincipal()
                .cast(GatewayAuthenticationToken.class)
                .map(authentication -> {
                    var identity = authentication.getPrincipal();
                    String path = exchange.getRequest().getPath().value();
                    String endpoint = path.startsWith("/api/v1/runs/")
                            ? "/api/v1/runs/*"
                            : path;
                    return sha256(identity.tenantId() + "\0" + identity.userId()
                            + "\0" + endpoint);
                });
    }

    private static String sha256(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(value.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }
}
