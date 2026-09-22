package com.morshan.financial.gateway.security;

public record GatewayIdentity(String tenantId, String userId, String role) {
    public GatewayIdentity {
        if (!tenantId.matches("[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")) {
            throw new IllegalArgumentException("invalid tenant id");
        }
        if (!userId.matches("[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}")) {
            throw new IllegalArgumentException("invalid user id");
        }
        if (!role.equals("researcher") && !role.equals("admin")) {
            throw new IllegalArgumentException("invalid role");
        }
    }
}
