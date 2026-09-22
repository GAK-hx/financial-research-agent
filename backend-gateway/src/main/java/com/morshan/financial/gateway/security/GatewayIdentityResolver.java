package com.morshan.financial.gateway.security;

import com.morshan.financial.gateway.config.GatewayProperties;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Mono;

@Component
public class GatewayIdentityResolver {
    private final GatewayProperties properties;
    private final ReactiveJwtDecoder jwtDecoder;
    private final List<ApiClient> clients;

    public GatewayIdentityResolver(
            GatewayProperties properties,
            ObjectProvider<ReactiveJwtDecoder> jwtDecoderProvider) {
        this.properties = properties;
        this.jwtDecoder = jwtDecoderProvider.getIfAvailable();
        this.clients = parseClients(properties);
    }

    public Mono<GatewayIdentity> resolve(String credential) {
        for (ApiClient client : clients) {
            if (constantTimeEquals(credential, client.credential())) {
                return Mono.just(client.identity());
            }
        }
        if (jwtDecoder == null) {
            return Mono.empty();
        }
        return jwtDecoder.decode(credential)
                .flatMap(jwt -> {
                    String tenant = jwt.getClaimAsString(
                            properties.getSecurity().getJwtTenantClaim());
                    String user = jwt.getSubject();
                    String role = claimRole(
                            jwt.getClaims().get(
                                    properties.getSecurity().getJwtRoleClaim()));
                    if (tenant == null || user == null) {
                        return Mono.empty();
                    }
                    try {
                        return Mono.just(new GatewayIdentity(tenant, user, role));
                    } catch (IllegalArgumentException ignored) {
                        return Mono.empty();
                    }
                })
                .onErrorResume(ignored -> Mono.empty());
    }

    private static List<ApiClient> parseClients(GatewayProperties properties) {
        List<ApiClient> result = new ArrayList<>();
        GatewayProperties.Security security = properties.getSecurity();
        String defaultCredential = security.getExternalApiKey().isBlank()
                ? properties.getInternalApiKey()
                : security.getExternalApiKey();
        if (!defaultCredential.isBlank()) {
            result.add(new ApiClient(
                    defaultCredential,
                    new GatewayIdentity(
                            security.getDefaultTenantId(),
                            security.getDefaultUserId(),
                            normalizeRole(security.getDefaultRole()))));
        }
        if (!security.getApiClients().isBlank()) {
            for (String encoded : security.getApiClients().split(";")) {
                String[] fields = encoded.strip().split("\\|", -1);
                if (fields.length != 4 || fields[0].isBlank()) {
                    throw new IllegalArgumentException(
                            "GATEWAY_SECURITY_API_CLIENTS entry must be key|tenant|user|role");
                }
                result.add(new ApiClient(
                        fields[0],
                        new GatewayIdentity(
                                fields[1], fields[2], normalizeRole(fields[3]))));
            }
        }
        return List.copyOf(result);
    }

    private static boolean constantTimeEquals(String left, String right) {
        return MessageDigest.isEqual(
                left.getBytes(StandardCharsets.UTF_8),
                right.getBytes(StandardCharsets.UTF_8));
    }

    private static String claimRole(Object claim) {
        if (claim instanceof Collection<?> collection && !collection.isEmpty()) {
            return normalizeRole(String.valueOf(collection.iterator().next()));
        }
        return normalizeRole(claim == null ? "researcher" : String.valueOf(claim));
    }

    private static String normalizeRole(String value) {
        String normalized = value.toLowerCase().replace("role_", "");
        return normalized.equals("admin") ? "admin" : "researcher";
    }

    private record ApiClient(String credential, GatewayIdentity identity) {}
}
