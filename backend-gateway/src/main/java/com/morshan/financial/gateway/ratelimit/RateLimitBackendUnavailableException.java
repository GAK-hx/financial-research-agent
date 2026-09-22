package com.morshan.financial.gateway.ratelimit;

public final class RateLimitBackendUnavailableException extends RuntimeException {
    public RateLimitBackendUnavailableException() {
        super("rate limit backend unavailable");
    }
}
