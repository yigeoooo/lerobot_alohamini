package com.lerobot.saas.common.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "saas.storage")
public record StorageProperties(String basePath, String datasetPath) {
}
