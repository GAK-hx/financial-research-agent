package com.morshan.financial.gateway.config;

import jakarta.annotation.PostConstruct;
import java.net.URI;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "gateway")
public class GatewayProperties {
    private URI pythonBaseUrl = URI.create("http://job-api:8000");
    private String internalApiKey = "";
    private final Security security = new Security();
    private final RateLimit rateLimit = new RateLimit();

    public URI getPythonBaseUrl() {
        return pythonBaseUrl;
    }

    public void setPythonBaseUrl(URI pythonBaseUrl) {
        this.pythonBaseUrl = pythonBaseUrl;
    }

    public String getInternalApiKey() {
        return internalApiKey;
    }

    public void setInternalApiKey(String internalApiKey) {
        this.internalApiKey = internalApiKey;
    }

    public Security getSecurity() {
        return security;
    }

    public RateLimit getRateLimit() {
        return rateLimit;
    }

    @PostConstruct
    void validate() {
        if (internalApiKey == null || internalApiKey.isBlank()) {
            throw new IllegalStateException("gateway.internal-api-key must be configured");
        }
        if (rateLimit.replenishRate <= 0
                || rateLimit.burstCapacity <= 0
                || rateLimit.requestedTokens <= 0
                || rateLimit.requestedTokens > rateLimit.burstCapacity) {
            throw new IllegalStateException("gateway rate-limit values are invalid");
        }
    }

    public static class Security {
        private String externalApiKey = "";
        private String apiClients = "";
        private String defaultTenantId = "local-gateway";
        private String defaultUserId = "local-gateway";
        private String defaultRole = "admin";
        private String jwtJwkSetUri = "";
        private String jwtTenantClaim = "tenant_id";
        private String jwtRoleClaim = "role";

        public String getExternalApiKey() {
            return externalApiKey;
        }

        public void setExternalApiKey(String externalApiKey) {
            this.externalApiKey = externalApiKey;
        }

        public String getApiClients() {
            return apiClients;
        }

        public void setApiClients(String apiClients) {
            this.apiClients = apiClients;
        }

        public String getDefaultTenantId() {
            return defaultTenantId;
        }

        public void setDefaultTenantId(String defaultTenantId) {
            this.defaultTenantId = defaultTenantId;
        }

        public String getDefaultUserId() {
            return defaultUserId;
        }

        public void setDefaultUserId(String defaultUserId) {
            this.defaultUserId = defaultUserId;
        }

        public String getDefaultRole() {
            return defaultRole;
        }

        public void setDefaultRole(String defaultRole) {
            this.defaultRole = defaultRole;
        }

        public String getJwtJwkSetUri() {
            return jwtJwkSetUri;
        }

        public void setJwtJwkSetUri(String jwtJwkSetUri) {
            this.jwtJwkSetUri = jwtJwkSetUri;
        }

        public String getJwtTenantClaim() {
            return jwtTenantClaim;
        }

        public void setJwtTenantClaim(String jwtTenantClaim) {
            this.jwtTenantClaim = jwtTenantClaim;
        }

        public String getJwtRoleClaim() {
            return jwtRoleClaim;
        }

        public void setJwtRoleClaim(String jwtRoleClaim) {
            this.jwtRoleClaim = jwtRoleClaim;
        }
    }

    public static class RateLimit {
        private int replenishRate = 5;
        private int burstCapacity = 10;
        private int requestedTokens = 1;

        public int getReplenishRate() {
            return replenishRate;
        }

        public void setReplenishRate(int replenishRate) {
            this.replenishRate = replenishRate;
        }

        public int getBurstCapacity() {
            return burstCapacity;
        }

        public void setBurstCapacity(int burstCapacity) {
            this.burstCapacity = burstCapacity;
        }

        public int getRequestedTokens() {
            return requestedTokens;
        }

        public void setRequestedTokens(int requestedTokens) {
            this.requestedTokens = requestedTokens;
        }
    }
}
