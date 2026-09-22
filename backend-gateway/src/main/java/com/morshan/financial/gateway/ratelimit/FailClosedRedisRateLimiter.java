package com.morshan.financial.gateway.ratelimit;

import java.util.List;
import org.springframework.cloud.gateway.filter.ratelimit.RateLimiter;
import org.springframework.cloud.gateway.filter.ratelimit.RedisRateLimiter;
import org.springframework.cloud.gateway.support.ConfigurationService;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;
import reactor.core.publisher.Mono;

/** Converts Spring Cloud Gateway's Redis-error fail-open sentinel into an error. */
public final class FailClosedRedisRateLimiter extends RedisRateLimiter {
    public FailClosedRedisRateLimiter(
            ReactiveStringRedisTemplate redisTemplate,
            RedisScript<List<Long>> script,
            ConfigurationService configurationService) {
        super(redisTemplate, script, configurationService);
    }

    @Override
    public Mono<RateLimiter.Response> isAllowed(String routeId, String id) {
        return super.isAllowed(routeId, id).flatMap(response -> {
            String remaining = response.getHeaders().get(getRemainingHeader());
            if (response.isAllowed() && "-1".equals(remaining)) {
                return Mono.error(new RateLimitBackendUnavailableException());
            }
            return Mono.just(response);
        });
    }
}
