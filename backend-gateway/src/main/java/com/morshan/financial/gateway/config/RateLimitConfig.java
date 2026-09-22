package com.morshan.financial.gateway.config;

import com.morshan.financial.gateway.ratelimit.FailClosedRedisRateLimiter;
import java.util.List;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.cloud.gateway.filter.ratelimit.RedisRateLimiter;
import org.springframework.cloud.gateway.support.ConfigurationService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.ReactiveStringRedisTemplate;
import org.springframework.data.redis.core.script.RedisScript;

@Configuration
public class RateLimitConfig {
    @Bean
    RedisRateLimiter redisRateLimiter(
            ReactiveStringRedisTemplate redisTemplate,
            @Qualifier("redisRequestRateLimiterScript") RedisScript<List<Long>> script,
            ConfigurationService configurationService) {
        return new FailClosedRedisRateLimiter(redisTemplate, script, configurationService);
    }
}
