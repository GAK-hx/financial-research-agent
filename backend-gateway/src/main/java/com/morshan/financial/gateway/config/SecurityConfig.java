package com.morshan.financial.gateway.config;

import com.morshan.financial.gateway.security.GatewayAuthenticationToken;
import com.morshan.financial.gateway.security.GatewayIdentityResolver;
import java.nio.charset.StandardCharsets;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.authentication.BadCredentialsException;
import org.springframework.security.authentication.ReactiveAuthenticationManager;
import org.springframework.security.config.annotation.web.reactive.EnableWebFluxSecurity;
import org.springframework.security.config.web.server.SecurityWebFiltersOrder;
import org.springframework.security.config.web.server.ServerHttpSecurity;
import org.springframework.security.oauth2.jwt.NimbusReactiveJwtDecoder;
import org.springframework.security.oauth2.jwt.ReactiveJwtDecoder;
import org.springframework.security.web.server.SecurityWebFilterChain;
import org.springframework.security.web.server.authentication.AuthenticationWebFilter;
import org.springframework.security.web.server.authentication.ServerAuthenticationEntryPointFailureHandler;
import org.springframework.security.web.server.authentication.WebFilterChainServerAuthenticationSuccessHandler;
import org.springframework.security.web.server.context.NoOpServerSecurityContextRepository;
import reactor.core.publisher.Mono;

@Configuration
@EnableWebFluxSecurity
public class SecurityConfig {
    @Bean
    @ConditionalOnExpression("'${gateway.security.jwt-jwk-set-uri:}' != ''")
    ReactiveJwtDecoder jwtDecoder(GatewayProperties properties) {
        return NimbusReactiveJwtDecoder.withJwkSetUri(
                        properties.getSecurity().getJwtJwkSetUri())
                .build();
    }

    @Bean
    SecurityWebFilterChain springSecurityFilterChain(
            ServerHttpSecurity http,
            GatewayIdentityResolver identityResolver) {
        ReactiveAuthenticationManager manager = authentication ->
                identityResolver.resolve(String.valueOf(authentication.getCredentials()))
                        .map(GatewayAuthenticationToken::new)
                        .cast(org.springframework.security.core.Authentication.class)
                        .switchIfEmpty(Mono.error(
                                new BadCredentialsException("invalid credential")));

        AuthenticationWebFilter authentication = new AuthenticationWebFilter(manager);
        authentication.setSecurityContextRepository(
                NoOpServerSecurityContextRepository.getInstance());
        authentication.setServerAuthenticationConverter(exchange -> {
            String value = exchange.getRequest().getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
            if (value == null || !value.regionMatches(true, 0, "Bearer ", 0, 7)) {
                return Mono.empty();
            }
            String credential = value.substring(7).strip();
            if (credential.isEmpty()) {
                return Mono.empty();
            }
            return Mono.just(new org.springframework.security.authentication.UsernamePasswordAuthenticationToken(
                    credential, credential));
        });
        var entryPoint = (org.springframework.security.web.server.ServerAuthenticationEntryPoint)
                (exchange, ignored) -> {
                    exchange.getResponse().setStatusCode(HttpStatus.UNAUTHORIZED);
                    exchange.getResponse().getHeaders().setContentType(MediaType.APPLICATION_JSON);
                    exchange.getResponse().getHeaders().set(
                            HttpHeaders.WWW_AUTHENTICATE, "Bearer");
                    byte[] body = "{\"error\":{\"code\":\"AUTHENTICATION_REQUIRED\",\"message\":\"valid bearer credential required\"}}"
                            .getBytes(StandardCharsets.UTF_8);
                    DataBuffer buffer = exchange.getResponse().bufferFactory().wrap(body);
                    return exchange.getResponse().writeWith(Mono.just(buffer));
                };
        authentication.setAuthenticationFailureHandler(
                new ServerAuthenticationEntryPointFailureHandler(entryPoint));
        authentication.setAuthenticationSuccessHandler(
                new WebFilterChainServerAuthenticationSuccessHandler());

        return http
                .csrf(ServerHttpSecurity.CsrfSpec::disable)
                .httpBasic(ServerHttpSecurity.HttpBasicSpec::disable)
                .formLogin(ServerHttpSecurity.FormLoginSpec::disable)
                .logout(ServerHttpSecurity.LogoutSpec::disable)
                .securityContextRepository(NoOpServerSecurityContextRepository.getInstance())
                .authorizeExchange(exchange -> exchange
                        .pathMatchers("/actuator/health/**", "/actuator/info").permitAll()
                        .anyExchange().authenticated())
                .exceptionHandling(errors -> errors.authenticationEntryPoint(entryPoint))
                .addFilterAt(authentication, SecurityWebFiltersOrder.AUTHENTICATION)
                .build();
    }
}
