package com.lerobot.saas.common.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "saas.jwt")
public record JwtProperties(String secret, long expireHours) {
}
