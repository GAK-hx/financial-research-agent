package com.morshan.financial.gateway;

import com.morshan.financial.gateway.config.GatewayProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(GatewayProperties.class)
public class BackendGatewayApplication {
    public static void main(String[] args) {
        SpringApplication.run(BackendGatewayApplication.class, args);
    }
}
