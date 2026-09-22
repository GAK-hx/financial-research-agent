package com.morshan.financial.gateway.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.morshan.financial.gateway.config.GatewayProperties;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.support.DefaultListableBeanFactory;
import reactor.test.StepVerifier;

class GatewayIdentityResolverTest {
    @Test
    void resolvesDefaultApiKeyWithoutTrustingRequestHeaders() {
        GatewayProperties properties = new GatewayProperties();
        properties.setInternalApiKey("internal-secret");
        properties.getSecurity().setExternalApiKey("external-secret");
        properties.getSecurity().setDefaultTenantId("tenant-a");
        properties.getSecurity().setDefaultUserId("user-a");
        properties.getSecurity().setDefaultRole("researcher");
        var provider = new DefaultListableBeanFactory()
                .getBeanProvider(org.springframework.security.oauth2.jwt.ReactiveJwtDecoder.class);
        GatewayIdentityResolver resolver = new GatewayIdentityResolver(properties, provider);

        StepVerifier.create(resolver.resolve("external-secret"))
                .assertNext(identity -> {
                    assertThat(identity.tenantId()).isEqualTo("tenant-a");
                    assertThat(identity.userId()).isEqualTo("user-a");
                    assertThat(identity.role()).isEqualTo("researcher");
                })
                .verifyComplete();
        StepVerifier.create(resolver.resolve("wrong-secret")).verifyComplete();
    }

    @Test
    void resolvesMultipleApiClientsAndNormalizesRole() {
        GatewayProperties properties = new GatewayProperties();
        properties.getSecurity().setApiClients(
                "key-a|tenant-a|user-a|researcher;key-b|tenant-b|user-b|ROLE_ADMIN");
        var provider = new DefaultListableBeanFactory()
                .getBeanProvider(org.springframework.security.oauth2.jwt.ReactiveJwtDecoder.class);
        GatewayIdentityResolver resolver = new GatewayIdentityResolver(properties, provider);

        StepVerifier.create(resolver.resolve("key-b"))
                .assertNext(identity -> {
                    assertThat(identity.tenantId()).isEqualTo("tenant-b");
                    assertThat(identity.userId()).isEqualTo("user-b");
                    assertThat(identity.role()).isEqualTo("admin");
                })
                .verifyComplete();
    }
}
