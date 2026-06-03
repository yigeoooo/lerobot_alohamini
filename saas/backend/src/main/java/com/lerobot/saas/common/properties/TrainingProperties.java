package com.lerobot.saas.common.properties;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "saas.training")
public record TrainingProperties(String outputRoot, String logRoot, String condaSh, String condaEnv, String workDir) {
}
