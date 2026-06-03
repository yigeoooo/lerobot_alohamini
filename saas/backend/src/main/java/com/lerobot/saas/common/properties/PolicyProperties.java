package com.lerobot.saas.common.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "saas.policy")
public record PolicyProperties(String scanPath) {
}
