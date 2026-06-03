package com.lerobot.saas;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication
@MapperScan(basePackages = {
        "com.lerobot.saas.auth.dao",
        "com.lerobot.saas.organization.dao",
        "com.lerobot.saas.permission.dao",
        "com.lerobot.saas.user.dao",
        "com.lerobot.saas.icon.dao"
})
@ConfigurationPropertiesScan
public class SaasApplication {

    public static void main(String[] args) {
        SpringApplication.run(SaasApplication.class, args);
    }
}
