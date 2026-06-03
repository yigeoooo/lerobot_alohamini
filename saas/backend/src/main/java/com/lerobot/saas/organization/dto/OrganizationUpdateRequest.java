package com.lerobot.saas.organization.dto;

import jakarta.validation.constraints.NotBlank;
import lombok.Data;

@Data
public class OrganizationUpdateRequest {

    @NotBlank(message = "组织名称不能为空")
    private String organizationName;

    private String organizationCode;

    private String description;
}
