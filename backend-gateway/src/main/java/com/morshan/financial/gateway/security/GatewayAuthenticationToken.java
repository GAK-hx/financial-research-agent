package com.morshan.financial.gateway.security;

import java.util.List;
import org.springframework.security.authentication.AbstractAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

public final class GatewayAuthenticationToken extends AbstractAuthenticationToken {
    private final GatewayIdentity identity;

    public GatewayAuthenticationToken(GatewayIdentity identity) {
        super(List.of(new SimpleGrantedAuthority("ROLE_" + identity.role().toUpperCase())));
        this.identity = identity;
        setAuthenticated(true);
    }

    @Override
    public GatewayIdentity getPrincipal() {
        return identity;
    }

    @Override
    public Object getCredentials() {
        return "";
    }
}
